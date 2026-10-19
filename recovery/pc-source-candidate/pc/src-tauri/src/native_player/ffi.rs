// libmpv C ABI bindings (manual, minimal subset).
//
// We don't pull in the libmpv2 wrapper crate because its high-level Rust
// surface only exposes the OpenGL render path through `RenderParamApiType`,
// and we need direct access to `mpv_render_param` so we can pass the
// MPV_RENDER_PARAM_OPENGL_INIT_PARAMS struct (with our own get_proc_address
// callback) ourselves. This file just declares the symbols we need from
// libmpv-2.dll; the linker resolves them via build.rs.
//
// Header references:
//   pc/vendor/mpv-dev/include/mpv/client.h
//   pc/vendor/mpv-dev/include/mpv/render.h
//   pc/vendor/mpv-dev/include/mpv/render_gl.h
//
// Threading rules (from render.h §Threading):
//   - All mpv_render_* calls happen on the GL thread (the one with the GL
//     context current), and only one at a time per render_context.
//   - Update callback may fire on ANY thread; from there we only post a
//     wakeup to the GL thread, never call mpv_* directly.
//   - mpv_command/_set_property/_get_property are safe from non-GL threads.

#![allow(non_camel_case_types, non_snake_case, dead_code)]

use std::os::raw::{c_char, c_int, c_void};

// ---- Opaque handles -------------------------------------------------------

#[repr(C)]
pub struct mpv_handle {
    _private: [u8; 0],
}
#[repr(C)]
pub struct mpv_render_context {
    _private: [u8; 0],
}

// ---- Errors ---------------------------------------------------------------

pub const MPV_ERROR_SUCCESS: c_int = 0;

// ---- Formats (subset) -----------------------------------------------------

pub const MPV_FORMAT_NONE: c_int = 0;
pub const MPV_FORMAT_STRING: c_int = 1;
pub const MPV_FORMAT_FLAG: c_int = 3;
pub const MPV_FORMAT_INT64: c_int = 4;
pub const MPV_FORMAT_DOUBLE: c_int = 5;
pub const MPV_FORMAT_NODE: c_int = 6;

// ---- Events (subset, the ones we actually consume) -----------------------

pub const MPV_EVENT_NONE: c_int = 0;
pub const MPV_EVENT_SHUTDOWN: c_int = 1;
pub const MPV_EVENT_LOG_MESSAGE: c_int = 2;
pub const MPV_EVENT_END_FILE: c_int = 7;
pub const MPV_EVENT_FILE_LOADED: c_int = 8;
pub const MPV_EVENT_VIDEO_RECONFIG: c_int = 17;
pub const MPV_EVENT_PLAYBACK_RESTART: c_int = 21;
pub const MPV_EVENT_PROPERTY_CHANGE: c_int = 22;

// END_FILE reason 值（mpv client.h MPV_END_FILE_REASON_*）。
// 我们只关心 EOF —— 视频自然播完，触发"自动下一集"。其他 reason
// （STOP=用户主动 stop / SwitchResource、QUIT、ERROR、REDIRECT）
// 都不应该触发自动播下一集。
pub const MPV_END_FILE_REASON_EOF: c_int = 0;
pub const MPV_END_FILE_REASON_STOP: c_int = 2;
pub const MPV_END_FILE_REASON_QUIT: c_int = 3;
pub const MPV_END_FILE_REASON_ERROR: c_int = 4;
pub const MPV_END_FILE_REASON_REDIRECT: c_int = 5;

#[repr(C)]
pub struct mpv_event {
    pub event_id: c_int,
    pub error: c_int,
    pub reply_userdata: u64,
    pub data: *mut c_void,
}

#[repr(C)]
pub struct mpv_event_property {
    pub name: *const c_char,
    pub format: c_int,
    pub data: *mut c_void,
}

/// LOG_MESSAGE 事件 data 指向的结构（mpv client.h `mpv_event_log_message`）。
/// prefix 是模块名（"vd"/"d3d11va"/"cache"…），level 是字符串等级
/// （"v"/"info"/"warn"/"error"），text 是带换行的人类可读消息。
#[repr(C)]
pub struct mpv_event_log_message {
    pub prefix: *const c_char,
    pub level: *const c_char,
    pub text: *const c_char,
    pub log_level: c_int,
}

/// END_FILE 事件的 data 指向的结构（mpv client.h `mpv_event_end_file`）。
/// 我们只读 `reason` —— 0=EOF（自然播完）触发"自动下一集"。后面三个
/// playlist_* 字段 mpv 0.36+ 才有，非空 playlist 才有意义；CyberStream
/// 不用 mpv playlist（每集是独立 loadfile），不读它们也不会出错。
#[repr(C)]
pub struct mpv_event_end_file {
    pub reason: c_int,
    pub error: c_int,
    pub playlist_entry_id: i64,
    pub playlist_insert_id: i64,
    pub playlist_insert_num_entries: c_int,
}

// ---- Render API params (subset, see render.h) ----------------------------

pub const MPV_RENDER_PARAM_INVALID: c_int = 0;
pub const MPV_RENDER_PARAM_API_TYPE: c_int = 1;
pub const MPV_RENDER_PARAM_OPENGL_INIT_PARAMS: c_int = 2;
pub const MPV_RENDER_PARAM_OPENGL_FBO: c_int = 3;
pub const MPV_RENDER_PARAM_FLIP_Y: c_int = 4;
pub const MPV_RENDER_PARAM_ADVANCED_CONTROL: c_int = 10;

pub const MPV_RENDER_API_TYPE_OPENGL: &[u8] = b"opengl\0";

#[repr(C)]
pub struct mpv_render_param {
    pub kind: c_int,
    pub data: *mut c_void,
}

#[repr(C)]
pub struct mpv_opengl_init_params {
    pub get_proc_address: unsafe extern "C" fn(ctx: *mut c_void, name: *const c_char) -> *mut c_void,
    pub get_proc_address_ctx: *mut c_void,
}

#[repr(C)]
pub struct mpv_opengl_fbo {
    pub fbo: c_int,
    pub w: c_int,
    pub h: c_int,
    pub internal_format: c_int,
}

// ---- Functions we link against -------------------------------------------

#[link(name = "libmpv-2", kind = "dylib")]
unsafe extern "C" {
    pub fn mpv_create() -> *mut mpv_handle;
    pub fn mpv_initialize(ctx: *mut mpv_handle) -> c_int;
    pub fn mpv_terminate_destroy(ctx: *mut mpv_handle);
    pub fn mpv_set_option_string(ctx: *mut mpv_handle, name: *const c_char, data: *const c_char) -> c_int;
    pub fn mpv_set_property_string(ctx: *mut mpv_handle, name: *const c_char, data: *const c_char) -> c_int;
    pub fn mpv_set_property(
        ctx: *mut mpv_handle,
        name: *const c_char,
        format: c_int,
        data: *mut c_void,
    ) -> c_int;
    pub fn mpv_get_property(
        ctx: *mut mpv_handle,
        name: *const c_char,
        format: c_int,
        data: *mut c_void,
    ) -> c_int;
    pub fn mpv_get_property_string(ctx: *mut mpv_handle, name: *const c_char) -> *mut c_char;
    pub fn mpv_command(ctx: *mut mpv_handle, args: *mut *const c_char) -> c_int;
    pub fn mpv_observe_property(
        ctx: *mut mpv_handle,
        reply_userdata: u64,
        name: *const c_char,
        format: c_int,
    ) -> c_int;
    pub fn mpv_wait_event(ctx: *mut mpv_handle, timeout: f64) -> *mut mpv_event;
    pub fn mpv_event_name(event_id: c_int) -> *const c_char;
    pub fn mpv_error_string(error: c_int) -> *const c_char;
    pub fn mpv_request_log_messages(ctx: *mut mpv_handle, min_level: *const c_char) -> c_int;
    pub fn mpv_free(data: *mut c_void);

    pub fn mpv_render_context_create(
        out: *mut *mut mpv_render_context,
        ctx: *mut mpv_handle,
        params: *mut mpv_render_param,
    ) -> c_int;
    pub fn mpv_render_context_set_update_callback(
        ctx: *mut mpv_render_context,
        callback: unsafe extern "C" fn(cb_ctx: *mut c_void),
        callback_ctx: *mut c_void,
    );
    pub fn mpv_render_context_update(ctx: *mut mpv_render_context) -> u64;
    pub fn mpv_render_context_render(
        ctx: *mut mpv_render_context,
        params: *mut mpv_render_param,
    ) -> c_int;
    pub fn mpv_render_context_report_swap(ctx: *mut mpv_render_context);
    pub fn mpv_render_context_free(ctx: *mut mpv_render_context);
}

// ---- Rust-side error helpers --------------------------------------------

/// Translate a libmpv negative return code into a human-readable message.
/// Returns "ok" on success.
pub fn err_string(code: c_int) -> String {
    if code >= 0 {
        return "ok".into();
    }
    unsafe {
        let p = mpv_error_string(code);
        if p.is_null() {
            return format!("mpv error {code} (no string)");
        }
        std::ffi::CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}
