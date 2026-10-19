// libmpv handle + render context + frame loop.
//
// Lifecycle:
//   1. mpv_create() → empty handle
//   2. set options (idle, terminal, hwdec, etc.) BEFORE initialize
//   3. mpv_initialize()
//   4. mpv_render_context_create with MPV_RENDER_API_TYPE_OPENGL +
//      mpv_opengl_init_params {get_proc_address = wgl resolver}
//   5. mpv_render_context_set_update_callback → posts a wakeup message
//   6. main loop: pump win messages → if mpv has a new frame
//      (signalled via the callback), call mpv_render_context_render with
//      mpv_opengl_fbo {fbo=0, w, h} → SwapBuffers
//   7. mpv_command(loadfile, url) → playback starts
//
// We keep mpv events on a tiny background thread that calls
// mpv_wait_event in a loop and forwards property-change / log /
// shutdown to channels the main thread polls. This isolates the GL
// thread from the libmpv ringbuffer drain and prevents the queue
// overflow described in client.h §MPV_EVENT_QUEUE_OVERFLOW.

use std::ffi::{c_void, CStr, CString};
use std::os::raw::c_int;
use std::ptr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use crate::native_player::ffi as mp;
use crate::native_player::window::PlayerWindow;

/// Owns the libmpv handle and its render context. Drop tears them down in
/// the right order (render context first, handle last; reverse-creation).
pub struct MpvPlayer {
    handle: *mut mp::mpv_handle,
    render: *mut mp::mpv_render_context,
    /// True when the update callback has fired since last render. Reset
    /// after every render() call.
    pending_frame: Arc<AtomicBool>,
}

unsafe impl Send for MpvPlayer {}

impl MpvPlayer {
    /// Raw mpv handle for code paths that need to call libmpv APIs
    /// outside this struct (property observers, action dispatch).
    /// Caller must ensure the handle is used on a thread allowed by
    /// libmpv's threading rules (see render.h §Threading).
    pub fn handle(&self) -> *mut mp::mpv_handle {
        self.handle
    }

    /// Create + initialise libmpv with options suited for a render-API
    /// embedded player (no terminal, no input subsystem, no fallback
    /// window, hwdec on, libass for subtitles).
    pub unsafe fn create() -> Result<Self, String> { unsafe {
        let handle = mp::mpv_create();
        if handle.is_null() {
            return Err("mpv_create returned NULL".into());
        }

        // Options that must be set BEFORE mpv_initialize.
        let presets: &[(&str, &str)] = &[
            ("terminal", "no"),       // Render API: no terminal log
            ("msg-level", "all=warn"), // Quieter output
            ("vo", "libmpv"),         // REQUIRED: tells mpv we'll drive
                                      // rendering via the render API.
                                      // Without this, mpv tries to open a
                                      // VO of its own.
            ("hwdec", "auto-safe"),   // Hardware decoding: D3D11VA on Win
            ("keep-open", "yes"),     // Stay alive on EOF for next file
            ("idle", "yes"),          // Allow idle without files queued
            ("input-default-bindings", "no"),
            ("input-vo-keyboard", "no"),
            ("input-cursor", "no"),
            ("osc", "no"),            // We draw our own controls
            // 4K HDR HEVC REMUX 启动优化：
            //   - cache-pause-initial=no：mpv 默认 yes 时会等 demuxer 缓到
            //     约 2s 才开始播；4K REMUX 100Mbps，解第一帧已经够慢，再
            //     叠加缓冲等待让"画面卡住但声音先出"的体感延长到 30~60s。
            //   - demuxer-max-bytes=1GiB：4K REMUX 默认 150MB ≈ 12s 太紧，
            //     一旦视频解码慢于 audio 推进，缓冲容易反复 underrun。
            //   - vd-lavc-threads=0：libavcodec 自动选并行度（默认会按 CPU
            //     核数走但有上限），4K HEVC 解码瓶颈在这里。
            //   - video-latency-hacks=yes：mpv 内部的低延迟启动开关，跳过
            //     一些"先看几帧再决定渲染节奏"的协商。
            ("cache", "yes"),
            ("cache-pause-initial", "no"),
            ("demuxer-max-bytes", "1GiB"),
            ("demuxer-max-back-bytes", "256MiB"),
            ("network-timeout", "30"),
            ("vd-lavc-threads", "0"),
            ("video-latency-hacks", "yes"),
            // mpv 日志拉到 v 级，让 hwdec 初始化 / 第一帧解码细节进 stderr。
            // 后续如果还有"画面卡 N 秒"的报障，cargo tauri dev 的终端能看到
            // 是 d3d11va init 卡了还是 libavcodec 等线程开起来了。
        ];

        for (k, v) in presets {
            let key = CString::new(*k).unwrap();
            let val = CString::new(*v).unwrap();
            let r = mp::mpv_set_option_string(handle, key.as_ptr(), val.as_ptr());
            if r < 0 {
                let msg = mp::err_string(r);
                mp::mpv_terminate_destroy(handle);
                return Err(format!("set_option {k}={v}: {msg}"));
            }
        }

        // mpv 日志：warn+ 已经覆盖了 hwdec init 失败 / 网络超时等关键消息，
        // v 级太啰嗦（每帧 video-margin 设属性都打），跑着跑着就刷屏了。
        // 排障时手动调到 v 即可。
        let _ = mp::mpv_request_log_messages(handle, c"warn".as_ptr() as _);

        let r = mp::mpv_initialize(handle);
        if r < 0 {
            let msg = mp::err_string(r);
            mp::mpv_terminate_destroy(handle);
            return Err(format!("mpv_initialize: {msg}"));
        }

        Ok(MpvPlayer {
            handle,
            render: ptr::null_mut(),
            pending_frame: Arc::new(AtomicBool::new(true)),
        })
    }}

    /// Initialise the render context. Must be called AFTER the GL context
    /// is current on the calling thread, AND before any video starts to
    /// play (otherwise mpv falls back to creating its own VO/window).
    pub unsafe fn init_render(&mut self) -> Result<(), String> { unsafe {
        if !self.render.is_null() {
            return Ok(());
        }

        let api_type = mp::MPV_RENDER_API_TYPE_OPENGL.as_ptr() as *mut c_void;

        let mut init = mp::mpv_opengl_init_params {
            get_proc_address: get_proc_address_thunk,
            get_proc_address_ctx: ptr::null_mut(),
        };

        // ADVANCED_CONTROL=0 (simple mode): mpv saves/restores its own GL
        // state at render() entry/exit. With egui_glow painting on top in
        // the same default framebuffer, leaving this at 1 made egui's
        // residual state (BLEND, SCISSOR_TEST, custom shader, viewport)
        // corrupt mpv's next frame — see plan v3 §8 risk row #1.
        let mut adv: c_int = 0;

        let mut params = [
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_API_TYPE,
                data: api_type,
            },
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,
                data: &mut init as *mut _ as *mut c_void,
            },
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_ADVANCED_CONTROL,
                data: &mut adv as *mut _ as *mut c_void,
            },
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_INVALID,
                data: ptr::null_mut(),
            },
        ];

        let mut ctx: *mut mp::mpv_render_context = ptr::null_mut();
        let r = mp::mpv_render_context_create(&mut ctx, self.handle, params.as_mut_ptr());
        if r < 0 {
            return Err(format!("mpv_render_context_create: {}", mp::err_string(r)));
        }
        self.render = ctx;

        // Wire up the update callback. This is invoked from arbitrary mpv
        // threads when a new frame is available; we just flip a flag so
        // the main GL thread knows to call render().
        let flag = Arc::clone(&self.pending_frame);
        let leaked = Arc::into_raw(flag) as *mut c_void;
        mp::mpv_render_context_set_update_callback(
            self.render,
            update_callback_thunk,
            leaked,
        );

        Ok(())
    }}

    /// True if a new frame is waiting to be drawn. The flag is consumed
    /// by `render_frame`, so the caller drives the loop:
    ///   if has_frame() { render_frame(w,h); swap_buffers(); }
    pub fn has_frame(&self) -> bool {
        self.pending_frame.load(Ordering::Acquire)
    }

    /// Force-draw on the next loop iteration, e.g. after a window resize
    /// where mpv hasn't actually queued a new frame but we still need to
    /// repaint to fill the new viewport.
    pub fn request_redraw(&self) {
        self.pending_frame.store(true, Ordering::Release);
    }

    /// Pull at most one new frame from mpv into FBO 0 (the default
    /// framebuffer of the current GL context).
    pub unsafe fn render_frame(&self, fbo_w: i32, fbo_h: i32) -> Result<(), String> { unsafe {
        if self.render.is_null() {
            return Err("render context not initialised".into());
        }
        // Reset the pending flag BEFORE rendering so a callback that
        // fires during render() still gets honoured next iteration.
        self.pending_frame.store(false, Ordering::Release);

        let mut fbo = mp::mpv_opengl_fbo {
            fbo: 0,
            w: fbo_w,
            h: fbo_h,
            internal_format: 0,
        };
        // mpv's GL renderer assumes the GL convention where the FBO origin
        // is at the BOTTOM-left. The Win32 wgl default framebuffer presents
        // with origin at the TOP-left when SwapBuffers hands the surface to
        // DWM, so without flipping we'd see the picture upside down. Setting
        // FLIP_Y=1 tells mpv to invert vertically before writing.
        let mut flip: c_int = 1;

        let mut params = [
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_OPENGL_FBO,
                data: &mut fbo as *mut _ as *mut c_void,
            },
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_FLIP_Y,
                data: &mut flip as *mut _ as *mut c_void,
            },
            mp::mpv_render_param {
                kind: mp::MPV_RENDER_PARAM_INVALID,
                data: ptr::null_mut(),
            },
        ];

        let r = mp::mpv_render_context_render(self.render, params.as_mut_ptr());
        if r < 0 {
            return Err(format!("render: {}", mp::err_string(r)));
        }
        Ok(())
    }}

    /// Tell mpv we just swapped buffers. Optional but improves vsync.
    pub unsafe fn report_swap(&self) {
        if !self.render.is_null() {
            unsafe { mp::mpv_render_context_report_swap(self.render); }
        }
    }

    /// Set a libmpv option that takes a string value, post-initialise.
    /// Used for things like `http-header-fields` and `start` that need
    /// to be configured per-loadfile rather than baked into create().
    pub fn set_option(&self, name: &str, value: &str) -> Result<(), String> {
        let key = std::ffi::CString::new(name).map_err(|e| e.to_string())?;
        let val = std::ffi::CString::new(value).map_err(|e| e.to_string())?;
        let r = unsafe { mp::mpv_set_option_string(self.handle, key.as_ptr(), val.as_ptr()) };
        if r < 0 {
            return Err(format!("set_option {name}: {}", mp::err_string(r)));
        }
        Ok(())
    }

    /// Set a libmpv property by string. Used at runtime for dynamic
    /// values like `video-margin-ratio-*` that reshape mpv's viewport
    /// (we use this to carve out room for the bottom bar / side panel
    /// so subtitles aren't covered by HUD chrome).
    pub fn set_property_str(&self, name: &str, value: &str) -> Result<(), String> {
        let key = std::ffi::CString::new(name).map_err(|e| e.to_string())?;
        let val = std::ffi::CString::new(value).map_err(|e| e.to_string())?;
        let r = unsafe { mp::mpv_set_property_string(self.handle, key.as_ptr(), val.as_ptr()) };
        if r < 0 {
            return Err(format!("set_property {name}: {}", mp::err_string(r)));
        }
        Ok(())
    }

    /// Read a libmpv property as a string. Used for properties whose
    /// shape changes too often to bake into a typed observer (most
    /// notably `track-list` — mpv serialises the whole thing to JSON,
    /// we parse with serde_json::Value).
    ///
    /// Returns `None` when mpv reports the property is unset (e.g. when
    /// no file is loaded yet) or when the call fails. Handles the
    /// `mpv_free` for the C-allocated string.
    pub fn get_property_string(&self, name: &str) -> Option<String> {
        let key = std::ffi::CString::new(name).ok()?;
        unsafe {
            let raw = mp::mpv_get_property_string(self.handle, key.as_ptr());
            if raw.is_null() {
                return None;
            }
            let cstr = CStr::from_ptr(raw);
            let owned = cstr.to_str().ok().map(|s| s.to_string());
            mp::mpv_free(raw as *mut c_void);
            owned
        }
    }

    /// Issue a libmpv command (e.g. ["loadfile", url]) and wait for
    /// completion synchronously. Suitable for one-shot loadfile in M3.1.
    pub unsafe fn command(&self, args: &[&str]) -> Result<(), String> { unsafe {
        let owned: Vec<CString> = args.iter()
            .map(|s| CString::new(*s).unwrap())
            .collect();
        let mut ptrs: Vec<*const _> = owned.iter().map(|c| c.as_ptr()).collect();
        ptrs.push(ptr::null());
        let r = mp::mpv_command(self.handle, ptrs.as_mut_ptr());
        if r < 0 {
            return Err(format!("mpv command {args:?}: {}", mp::err_string(r)));
        }
        Ok(())
    }}

    /// Drain pending events synchronously. Returns true if a SHUTDOWN
    /// event was seen — caller should stop the loop and tear down.
    pub unsafe fn drain_events(&self) -> bool { unsafe {
        loop {
            let ev = mp::mpv_wait_event(self.handle, 0.0); // poll
            if ev.is_null() {
                return false;
            }
            let id = (*ev).event_id;
            if id == mp::MPV_EVENT_NONE {
                return false;
            }
            if id == mp::MPV_EVENT_SHUTDOWN {
                return true;
            }
            if id == mp::MPV_EVENT_LOG_MESSAGE {
                // M3.1: stderr already gets mpv's own messages because we
                // set --terminal=no AFTER request_log_messages — keeping
                // this branch as a structured-logging hook for M3.5.
                let _ = (*ev).data;
            }
            // Other events ignored in M3.1.
        }
    }}
}

impl Drop for MpvPlayer {
    fn drop(&mut self) {
        unsafe {
            if !self.render.is_null() {
                mp::mpv_render_context_free(self.render);
                self.render = ptr::null_mut();
            }
            if !self.handle.is_null() {
                mp::mpv_terminate_destroy(self.handle);
                self.handle = ptr::null_mut();
            }
        }
    }
}

// ---- C-callable callbacks ------------------------------------------------

unsafe extern "C" fn update_callback_thunk(cb_ctx: *mut c_void) {
    // SAFETY: cb_ctx was created via Arc::into_raw on a clone we still
    // own through MpvPlayer.pending_frame; we just borrow it here.
    if cb_ctx.is_null() {
        return;
    }
    unsafe {
        let arc = Arc::from_raw(cb_ctx as *const AtomicBool);
        arc.store(true, Ordering::Release);
        // Re-leak: the Arc lives on inside MpvPlayer; this callback may
        // fire many times so we must not drop the strong ref here.
        let _ = Arc::into_raw(arc);
    }
}

unsafe extern "C" fn get_proc_address_thunk(_ctx: *mut c_void, name: *const i8) -> *mut c_void {
    if name.is_null() {
        return ptr::null_mut();
    }
    let cstr = unsafe { CStr::from_ptr(name) };
    let Ok(s) = cstr.to_str() else { return ptr::null_mut(); };
    unsafe { PlayerWindow::get_proc_address(s) }
}

// (Stub for log message struct removed; we'll add the real one in M3.5
// when wiring structured logging to the frontend.)
