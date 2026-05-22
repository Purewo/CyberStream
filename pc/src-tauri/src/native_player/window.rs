// Win32 window + wgl OpenGL context + mouse/keyboard event capture.
//
// Not reusing video_host.rs because that one was designed as a CHILD HWND
// inside the Tauri main window for `--wid` embedding (the failed v0~v2.1
// path). Here we want a separate top-level window owned by the native
// player module so the user is "in the player" while it's open.
//
// The wnd_proc captures mouse/keyboard events into an Arc<Mutex<Vec<...>>>
// stashed on the window via GWLP_USERDATA. The main thread drains them
// each frame and feeds them to egui as RawInput events.

use std::ffi::{c_void, CString};
use std::ptr;
use std::sync::{Arc, Mutex};

use windows::core::*;
use windows::Win32::Foundation::*;
use windows::Win32::Graphics::Gdi::*;
use windows::Win32::Graphics::OpenGL::*;
use windows::Win32::System::LibraryLoader::*;
use windows::Win32::UI::Input::KeyboardAndMouse::{VK_ESCAPE, VK_RETURN};
use windows::Win32::UI::WindowsAndMessaging::*;

const CLASS_NAME: PCWSTR = w!("CyberStreamNativePlayer");

/// Captured Win32 input events, drained by the main loop into egui.
#[derive(Debug, Clone)]
pub enum InputEvent {
    MouseMove { x: f32, y: f32 },
    MouseButton { button: MouseButton, pressed: bool, x: f32, y: f32 },
    /// Win32 fired a WM_LBUTTONDBLCLK — used to toggle fullscreen. We
    /// keep this separate from MouseButton because egui's own click
    /// detection works on simple press/release pairs and would
    /// mis-classify a real OS-level double-click.
    MouseDoubleClick { x: f32, y: f32 },
    MouseWheel { delta: f32 },
    Key { code: KeyCode, pressed: bool },
    /// Window resized — the main loop should query client_size and pass
    /// the new dimensions to egui.
    Resize,
}

#[derive(Debug, Clone, Copy)]
pub enum MouseButton {
    Left,
    Right,
    Middle,
}

#[derive(Debug, Clone, Copy)]
pub enum KeyCode {
    Escape,
    Space,
    Enter,
    Other(u32),
}

/// Handle to the per-window event queue. Cloneable so the wnd_proc
/// thread and the main thread can both access it.
pub type EventQueue = Arc<Mutex<Vec<InputEvent>>>;

/// Owned Win32 window + GL context + event queue. Drop tears them down.
pub struct PlayerWindow {
    pub hwnd: HWND,
    pub hdc: HDC,
    pub glrc: HGLRC,
    pub width: i32,
    pub height: i32,
    pub events: EventQueue,
    /// Cached pre-fullscreen window placement so we can restore the
    /// 1280×720 windowed look when the user toggles "全屏" off.
    saved_placement: std::cell::Cell<Option<WINDOWPLACEMENT>>,
    /// Cached pre-fullscreen window style (WS_OVERLAPPEDWINDOW vs popup
    /// without borders) so we can revert on toggle-off.
    saved_style: std::cell::Cell<Option<i32>>,
    /// Keep the boxed queue alive for the wnd_proc's lifetime; freed in
    /// Drop after DestroyWindow returns.
    _queue_box: Box<EventQueue>,
}

impl PlayerWindow {
    /// Create a windowed (1280×720, centered) borderless window with an
    /// OpenGL 3.3-capable wgl context current on the calling thread.
    pub unsafe fn create() -> Result<Self> { unsafe {
        register_class_once()?;
        let hinst = GetModuleHandleW(None)?;

        let cx_screen = GetSystemMetrics(SM_CXSCREEN);
        let cy_screen = GetSystemMetrics(SM_CYSCREEN);
        let w: i32 = 1280;
        let h: i32 = 720;
        let x = ((cx_screen - w) / 2).max(0);
        let y = ((cy_screen - h) / 2).max(0);

        let events: EventQueue = Arc::new(Mutex::new(Vec::with_capacity(64)));
        let queue_box: Box<EventQueue> = Box::new(events.clone());
        let queue_ptr = &*queue_box as *const EventQueue as isize;

        let hwnd = CreateWindowExW(
            WS_EX_APPWINDOW,
            CLASS_NAME,
            w!("CyberStream"),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN,
            x, y, w, h,
            None, None,
            Some(hinst.into()),
            None,
        )?;

        // Stash the queue pointer on the window so wnd_proc can find it.
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, queue_ptr);

        let hdc = GetDC(Some(hwnd));
        if hdc.is_invalid() {
            let _ = DestroyWindow(hwnd);
            return Err(Error::from_win32());
        }

        let pfd = PIXELFORMATDESCRIPTOR {
            nSize: std::mem::size_of::<PIXELFORMATDESCRIPTOR>() as u16,
            nVersion: 1,
            dwFlags: PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER,
            iPixelType: PFD_TYPE_RGBA,
            cColorBits: 32,
            cDepthBits: 24,
            cStencilBits: 8,
            iLayerType: PFD_MAIN_PLANE.0 as u8,
            ..Default::default()
        };
        let pf = ChoosePixelFormat(hdc, &pfd);
        if pf == 0 {
            ReleaseDC(Some(hwnd), hdc);
            let _ = DestroyWindow(hwnd);
            return Err(Error::from_win32());
        }
        SetPixelFormat(hdc, pf, &pfd)?;

        let glrc = wglCreateContext(hdc)?;
        wglMakeCurrent(hdc, glrc)?;

        Ok(PlayerWindow {
            hwnd, hdc, glrc,
            width: w, height: h,
            events,
            saved_placement: std::cell::Cell::new(None),
            saved_style: std::cell::Cell::new(None),
            _queue_box: queue_box,
        })
    }}

    /// Drain pending Win32 messages. Returns false when WM_QUIT was seen.
    pub unsafe fn pump_messages(&self) -> bool { unsafe {
        let mut msg = MSG::default();
        while PeekMessageW(&mut msg, None, 0, 0, PM_REMOVE).into() {
            if msg.message == WM_QUIT {
                return false;
            }
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        true
    }}

    /// Current client-area dimensions in pixels.
    pub unsafe fn client_size(&self) -> (i32, i32) { unsafe {
        let mut rc = RECT::default();
        if GetClientRect(self.hwnd, &mut rc).is_ok() {
            ((rc.right - rc.left).max(1), (rc.bottom - rc.top).max(1))
        } else {
            (self.width.max(1), self.height.max(1))
        }
    }}

    /// Take all queued input events. Called once per frame.
    pub fn drain_events(&self) -> Vec<InputEvent> {
        match self.events.lock() {
            Ok(mut q) => std::mem::take(&mut *q),
            Err(_) => Vec::new(),
        }
    }

    /// Present the current GL backbuffer.
    pub unsafe fn swap_buffers(&self) -> bool { unsafe {
        SwapBuffers(self.hdc).is_ok()
    }}

    /// Whether the window is currently in borderless OS fullscreen.
    pub fn is_fullscreen(&self) -> bool {
        self.saved_placement.get().is_some()
    }

    /// 主动结束播放循环：post WM_QUIT，让下一次 pump_messages 返回 false。
    /// Esc / 退出菜单走这条路；wnd_proc 里 WM_KEYDOWN 已经不再直接调
    /// PostQuitMessage 了，因为 Esc 现在是 "退出全屏 → 否则退出"。
    pub fn request_close(&self) {
        unsafe { PostQuitMessage(0) };
    }

    /// Toggle borderless fullscreen vs the regular OVERLAPPEDWINDOW
    /// state. The implementation is the standard "Raymond Chen" recipe
    /// for Win32 fullscreen toggling: cache placement + style, strip
    /// the title bar, expand to monitor work area; restore from cache
    /// on the second call.
    pub unsafe fn toggle_fullscreen(&self) { unsafe {
        if let Some(saved) = self.saved_placement.get() {
            // Coming back to windowed — restore style first, then placement.
            if let Some(style) = self.saved_style.get() {
                SetWindowLongW(self.hwnd, GWL_STYLE, style);
            }
            let _ = SetWindowPlacement(self.hwnd, &saved);
            SetWindowPos(
                self.hwnd, None, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED,
            ).ok();
            self.saved_placement.set(None);
            self.saved_style.set(None);
            return;
        }

        // Going fullscreen — capture current state, then resize to monitor.
        let mut wp = WINDOWPLACEMENT {
            length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
            ..Default::default()
        };
        if !GetWindowPlacement(self.hwnd, &mut wp).is_ok() {
            return;
        }
        let style = GetWindowLongW(self.hwnd, GWL_STYLE);
        self.saved_placement.set(Some(wp));
        self.saved_style.set(Some(style));

        // Pick the monitor the window currently sits on.
        let monitor = MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTOPRIMARY);
        let mut mi = MONITORINFO {
            cbSize: std::mem::size_of::<MONITORINFO>() as u32,
            ..Default::default()
        };
        if !GetMonitorInfoW(monitor, &mut mi).as_bool() {
            return;
        }

        SetWindowLongW(self.hwnd, GWL_STYLE, style & !(WS_OVERLAPPEDWINDOW.0 as i32));
        SetWindowPos(
            self.hwnd, None,
            mi.rcMonitor.left, mi.rcMonitor.top,
            mi.rcMonitor.right - mi.rcMonitor.left,
            mi.rcMonitor.bottom - mi.rcMonitor.top,
            SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED,
        ).ok();
    }}

    /// Resolve a wgl/GL function pointer. Used both by libmpv's
    /// get_proc_address and by glow::Context::from_loader_function.
    pub unsafe fn get_proc_address(name: &str) -> *mut c_void { unsafe {
        let cname = CString::new(name).unwrap();
        let p = wglGetProcAddress(PCSTR(cname.as_ptr() as *const u8));
        if let Some(p) = p {
            return p as *mut c_void;
        }
        // Fallback: load opengl32.dll once. Keeping it as a static is
        // safe enough for our use — single-threaded GL setup, no
        // mutation post-init.
        static mut OPENGL32: HMODULE = HMODULE(std::ptr::null_mut());
        if OPENGL32.is_invalid() {
            if let Ok(m) = GetModuleHandleW(w!("opengl32.dll")) {
                OPENGL32 = m;
            } else if let Ok(m) = LoadLibraryW(w!("opengl32.dll")) {
                OPENGL32 = m;
            } else {
                return ptr::null_mut();
            }
        }
        match GetProcAddress(OPENGL32, PCSTR(cname.as_ptr() as *const u8)) {
            Some(f) => f as *mut c_void,
            None => ptr::null_mut(),
        }
    }}
}

impl Drop for PlayerWindow {
    fn drop(&mut self) {
        unsafe {
            // Detach userdata first so wnd_proc no longer reads the queue
            // we're about to drop.
            SetWindowLongPtrW(self.hwnd, GWLP_USERDATA, 0);
            let _ = wglMakeCurrent(self.hdc, HGLRC(std::ptr::null_mut()));
            let _ = wglDeleteContext(self.glrc);
            ReleaseDC(Some(self.hwnd), self.hdc);
            let _ = DestroyWindow(self.hwnd);
        }
    }
}

// ---- Window proc + class ------------------------------------------------

unsafe fn push_event(h: HWND, ev: InputEvent) {
    unsafe {
        let raw = GetWindowLongPtrW(h, GWLP_USERDATA);
        if raw == 0 {
            return;
        }
        let q = &*(raw as *const EventQueue);
        if let Ok(mut g) = q.lock() {
            g.push(ev);
        }
    }
}

fn lparam_xy(l: LPARAM) -> (f32, f32) {
    let lo = (l.0 as i32) & 0xFFFF;
    let hi = ((l.0 as i32) >> 16) & 0xFFFF;
    let x = (lo as i16) as f32; // signed
    let y = (hi as i16) as f32;
    (x, y)
}

unsafe extern "system" fn wnd_proc(h: HWND, m: u32, w: WPARAM, l: LPARAM) -> LRESULT {
    unsafe {
        match m {
            WM_CLOSE => {
                PostQuitMessage(0);
                LRESULT(0)
            }
            WM_KEYDOWN | WM_SYSKEYDOWN => {
                let code = match w.0 as u32 {
                    x if x == VK_ESCAPE.0 as u32 => KeyCode::Escape,
                    x if x == VK_RETURN.0 as u32 => KeyCode::Enter,
                    0x20 => KeyCode::Space,
                    other => KeyCode::Other(other),
                };
                push_event(h, InputEvent::Key { code, pressed: true });
                // 不再在 wnd_proc 里直接 PostQuitMessage(0)。Esc 的语义现在
                // 是「退出全屏 → 否则退出播放器」（PotPlayer 同款），由主循环
                // 拿到 KeyCode::Escape 后视当时窗口状态决定。这里只把按键派
                // 出去就行——避免 wnd_proc 抢在 mod.rs 之前结束循环。
                DefWindowProcW(h, m, w, l)
            }
            WM_KEYUP | WM_SYSKEYUP => {
                let code = match w.0 as u32 {
                    x if x == VK_ESCAPE.0 as u32 => KeyCode::Escape,
                    x if x == VK_RETURN.0 as u32 => KeyCode::Enter,
                    0x20 => KeyCode::Space,
                    other => KeyCode::Other(other),
                };
                push_event(h, InputEvent::Key { code, pressed: false });
                DefWindowProcW(h, m, w, l)
            }
            WM_MOUSEMOVE => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseMove { x, y });
                LRESULT(0)
            }
            WM_LBUTTONDOWN => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Left, pressed: true, x, y,
                });
                LRESULT(0)
            }
            WM_LBUTTONUP => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Left, pressed: false, x, y,
                });
                LRESULT(0)
            }
            WM_LBUTTONDBLCLK => {
                let (x, y) = lparam_xy(l);
                // 双击连带派一对正常的 down+up，避免 egui 觉得鼠标卡在按下态。
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Left, pressed: true, x, y,
                });
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Left, pressed: false, x, y,
                });
                push_event(h, InputEvent::MouseDoubleClick { x, y });
                LRESULT(0)
            }
            WM_RBUTTONDOWN => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Right, pressed: true, x, y,
                });
                LRESULT(0)
            }
            WM_RBUTTONUP => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Right, pressed: false, x, y,
                });
                LRESULT(0)
            }
            WM_MBUTTONDOWN => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Middle, pressed: true, x, y,
                });
                LRESULT(0)
            }
            WM_MBUTTONUP => {
                let (x, y) = lparam_xy(l);
                push_event(h, InputEvent::MouseButton {
                    button: MouseButton::Middle, pressed: false, x, y,
                });
                LRESULT(0)
            }
            WM_MOUSEWHEEL => {
                let raw = (w.0 as i32) >> 16;
                let delta = (raw as i16) as f32 / 120.0; // WHEEL_DELTA = 120
                push_event(h, InputEvent::MouseWheel { delta });
                LRESULT(0)
            }
            WM_SIZE => {
                push_event(h, InputEvent::Resize);
                DefWindowProcW(h, m, w, l)
            }
            WM_ERASEBKGND => LRESULT(1), // GL/mpv owns every pixel
            _ => DefWindowProcW(h, m, w, l),
        }
    }
}

unsafe fn register_class_once() -> Result<()> {
    use std::sync::atomic::{AtomicBool, Ordering};
    static REGISTERED: AtomicBool = AtomicBool::new(false);
    if REGISTERED.load(Ordering::Relaxed) {
        return Ok(());
    }
    unsafe {
        let hinst = GetModuleHandleW(None)?;
        let cls = WNDCLASSW {
            // CS_DBLCLKS 让 wnd_proc 收到 WM_LBUTTONDBLCLK，否则双击只会
            // 拆成两次 LBUTTONDOWN/UP，没有专门事件可拿来切全屏。
            style: CS_OWNDC | CS_HREDRAW | CS_VREDRAW | CS_DBLCLKS,
            lpfnWndProc: Some(wnd_proc),
            hInstance: hinst.into(),
            hCursor: LoadCursorW(None, IDC_ARROW)?,
            hbrBackground: HBRUSH::default(),
            lpszClassName: CLASS_NAME,
            ..Default::default()
        };
        let atom = RegisterClassW(&cls);
        if atom == 0 {
            let e = GetLastError();
            if e != ERROR_CLASS_ALREADY_EXISTS {
                return Err(Error::from_win32());
            }
        }
        REGISTERED.store(true, Ordering::Relaxed);
        Ok(())
    }
}
