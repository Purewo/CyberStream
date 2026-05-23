// CyberStream PC native player · runtime state shared between the
// frame loop, the libmpv property observers, and the egui HUD.
//
// Design: a single `PlayerState` owned by the player thread, mutated
// only from that thread. mpv property changes arrive via mpv_wait_event
// and we apply them synchronously before drawing each frame, so there's
// no shared-mutability concern — egui reads the state, presses buttons
// emit `Action` values, and the frame loop applies actions back into
// libmpv via mpv_command / mpv_set_property.
//
// We deliberately avoid Arc<Mutex<...>>: the libmpv update callback
// fires on arbitrary threads, but we only flip an AtomicBool there
// (already handled in render.rs). Property observers run on the GL
// thread because mpv_wait_event is called there.

use std::ffi::{CStr, CString};
use std::os::raw::{c_int, c_void};
use std::ptr;

use crate::native_player::ffi as mp;
use crate::native_player::meta::{MovieMeta, ResourceMeta};

/// Reply IDs for mpv_observe_property. mpv reflects the same value back
/// to us in the event's reply_userdata field, which is how we tell which
/// property fired.
pub const PROP_TIME_POS: u64 = 1;
pub const PROP_DURATION: u64 = 2;
pub const PROP_PAUSE: u64 = 3;
pub const PROP_VOLUME: u64 = 4;
pub const PROP_PAUSED_FOR_CACHE: u64 = 5;
pub const PROP_FILENAME: u64 = 6;
pub const PROP_MUTE: u64 = 7;
pub const PROP_SPEED: u64 = 8;
pub const PROP_SID: u64 = 9;
pub const PROP_AID: u64 = 10;
/// `eof-reached`：mpv 在 keep-open=yes 下不会发 END_FILE，只会把这个
/// 属性翻成 yes 然后停在最后一帧。我们观察这个属性来触发"自动下一集"。
pub const PROP_EOF_REACHED: u64 = 11;

/// Single source of truth for what the HUD shows. Updated by
/// `PlayerState::apply_property_change` whenever an mpv property
/// observer fires.
#[derive(Default, Debug, Clone)]
pub struct PlayerState {
    pub time_pos: f64,
    pub duration: f64,
    pub paused: bool,
    pub volume: f64,
    pub buffering: bool,
    pub filename: String,
    /// Movie metadata for the right-side panel. `None` when the webview
    /// invoked us without forwarding the detail payload (test paths).
    pub movie: Option<MovieMeta>,
    /// The currently playing resource id — drives the highlight in the
    /// right-side panel and gets updated when the user picks a different
    /// episode / source.
    pub current_resource_id: Option<String>,
    /// True when the native window is in OS-fullscreen. Toggled by the
    /// "全屏" button in the HUD; the actual Win32 SetWindowPlacement
    /// call lives in window.rs (we just track intent here).
    pub fullscreen: bool,
    /// Active season tab in the right-side panel. None when the movie has
    /// no `seasons[]` (single-season show or movie). Initialised the first
    /// frame the panel is drawn — see `Hud` lazily computing this from
    /// `current_resource_id`.
    pub active_season: Option<i32>,
    /// Mute state. Cached from mpv `mute` property; `Action::ToggleMute`
    /// inverts via mpv `cycle mute`.
    pub muted: bool,
    /// Playback speed (1.0 = realtime). mpv `speed` property; HUD shows
    /// 0.5 / 1.0 / 1.25 / 1.5 / 2.0 dropdown.
    pub speed: f64,
    /// Currently active subtitle track id from mpv (`sid` property).
    /// mpv represents this as a number-or-"no" string; we stringify
    /// either way. `None` when mpv hasn't reported yet.
    pub current_sid: Option<String>,
    /// Currently active audio track id from mpv (`aid` property).
    pub current_aid: Option<String>,
    /// Last seen mpv `track-list` snapshot, parsed into the subset the
    /// HUD cares about. The frame loop pulls this on a timer because
    /// observing `track-list` directly with format=NODE is heavyweight
    /// — string snapshots every ~1s is plenty for a UI dropdown.
    pub tracks: Vec<TrackInfo>,
    /// 在线字幕搜索面板是否展开。Action::OpenSubtitleSearch 翻 true，
    /// Action::CloseSubtitleSearch 或 ✕ / Esc 翻 false。
    pub online_search_open: bool,
    /// 用户在搜索框里的当前关键词。OpenSubtitleSearch 第一次打开时主循环
    /// 会用 movie.title 预填充，之后由用户编辑 / Action::RunSubtitleSearch
    /// 覆盖。
    pub online_search_query: String,
    /// 搜索 / 预览 / 绑定的实时状态。worker 线程写、UI 线程读。
    /// 用 Arc<Mutex> 因为是真正的跨线程共享数据；其他字段全在 GL 线程
    /// 同步推进，没必要锁。
    pub online_search_state: std::sync::Arc<std::sync::Mutex<OnlineSubState>>,
    /// 已下载到临时文件、但用户尚未点「绑定」的在线字幕。每条对应 mpv 里
    /// 一个 external sub track（external_filename == tmp_path）。重启 / 切集
    /// 后清空——临时文件由 OS temp 目录自动回收。
    pub preview_subtitles: Vec<PreviewSub>,
    /// 当前正在「二次确认删除」的已绑定字幕 id —— UI 看到这一行时把
    /// 「✕」按钮换成「确定 / 取消」。Some(sid) 表示 sid 这条进入待确认态；
    /// 用户点确定 → 真删并清回 None；点取消或别处 → None。同时只允许
    /// 一条进入待确认态，避免菜单里多行同时变化看着乱。
    pub pending_delete_sid: Option<String>,
    /// 进入新资源后是否已经做过「自动选字幕」。优先级：已绑定 > 内嵌。
    /// 触发时机由主循环判断（必须等 mpv track-list 拉到、PROP_SID 至少
    /// 推送过一次再做决定，否则会跟 mpv 自己的 --slang 抢）。每次
    /// SwitchResource 重置为 false 让新资源能再选一次。
    pub auto_subtitle_done: bool,
    /// mpv 触发了 END_FILE(reason=EOF)——视频自然播完。主循环每帧检查
    /// 这个标志，如果 derive_prev_next 算得出 next，自动派发 SwitchResource
    /// 跳到下一集。一次性标志：消费后立刻清零。
    /// 不在 SwitchResource 路径里设置（用户切集走的是 STOP reason）。
    pub pending_auto_next: bool,
}

/// 在线字幕子系统的真值副本。所有跨线程通信都过这个 Mutex；UI 每帧 lock 一次
/// 读快照，worker 完成时 lock 一次写。锁住时间都是 O(几十 ns)，不会影响 60fps。
#[derive(Debug, Default)]
pub struct OnlineSubState {
    /// 搜索阶段：Idle 没跑过 / Loading 正在搜 / Loaded 拿到候选 / Error 出错
    pub search: SearchPhase,
    /// 当前正在 download 预览或 bind 的候选 id —— UI 据此显示 spinner / 禁用按钮。
    pub busy_candidate: Option<String>,
    /// 最近一次预览 / 绑定的状态行（"已预览：xxx" / "绑定失败：xxx"）。
    pub last_message: Option<String>,
}

#[derive(Debug, Default)]
pub enum SearchPhase {
    #[default]
    Idle,
    Loading,
    Loaded(Vec<OnlineCandidate>),
    Error(String),
}

/// 字幕候选 —— 后端 search 返回结构的子集，只挑 UI 要的字段。
#[derive(Debug, Clone)]
pub struct OnlineCandidate {
    pub candidate_id: String,
    pub label: String,
    pub source: String,
    pub language: Option<String>,
    pub format: Option<String>,
}

/// Subset of an mpv track-list entry we render in the audio/subtitle
/// dropdowns. Schema reference: mpv manual `track-list` property —
/// `id`, `type` (audio/video/sub), `selected`, `title`, `lang`, `codec`,
/// `external`. We don't strongly type it because mpv occasionally adds
/// fields and some embedded tracks omit half of them; the parser uses
/// `serde_json::Value` and tolerates missing pieces.
#[derive(Debug, Clone)]
pub struct TrackInfo {
    pub id: i64,
    pub kind: String, // "audio" | "video" | "sub"
    pub selected: bool,
    pub title: Option<String>,
    pub lang: Option<String>,
    pub codec: Option<String>,
    pub external: bool,
    /// mpv 给外挂字幕的来源——预览字幕通过临时文件路径回填，绑定字幕通过
    /// 网络 URL 回填。HUD 用它把当前选中的轨道反查回 PreviewSub / SubtitleMeta。
    pub external_filename: Option<String>,
}

/// 「在线 · 临时预览」字幕条目。生命周期 = 当前播放器进程；切集 / 退出后丢弃。
/// 在线字幕 worker 下载完字节并写好临时 .srt 后，主循环 push 一条到
/// PlayerState.preview_subtitles 并调用 mpv `sub-add <tmp_path> select`。
#[derive(Debug, Clone)]
pub struct PreviewSub {
    pub candidate_id: String,
    pub label: String,
    pub tmp_path: String,
    pub format: Option<String>,
}

impl PlayerState {
    /// Look up the resource currently playing, if any.
    pub fn current_resource(&self) -> Option<&ResourceMeta> {
        let movie = self.movie.as_ref()?;
        let id = self.current_resource_id.as_deref()?;
        movie.resources.iter().find(|r| r.id == id)
    }

    /// Replace `tracks` with whatever mpv `track-list` currently reports.
    /// Caller is expected to pull the JSON via `MpvPlayer::get_property_string`
    /// every ~1s and feed it in. Tolerant of missing fields — mpv
    /// occasionally adds new keys and embedded subs sometimes lack a
    /// title/lang. On parse failure we leave the cached list alone.
    pub fn refresh_tracks_from_json(&mut self, json: &str) {
        let Ok(val) = serde_json::from_str::<serde_json::Value>(json) else {
            return;
        };
        let Some(arr) = val.as_array() else { return };
        let mut out = Vec::with_capacity(arr.len());
        for item in arr {
            let id = item.get("id").and_then(|v| v.as_i64()).unwrap_or(0);
            let kind = item
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let selected = item
                .get("selected")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let title = item
                .get("title")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let lang = item
                .get("lang")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let codec = item
                .get("codec")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let external = item
                .get("external")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            // mpv 用 kebab-case；外挂字幕（包括 sub-add 进来的）会带 external-filename
            // 字段，是 sub-add 时给的 URL / 文件路径。HUD 用它反查 PreviewSub / 绑定字幕。
            let external_filename = item
                .get("external-filename")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            out.push(TrackInfo {
                id,
                kind,
                selected,
                title,
                lang,
                codec,
                external,
                external_filename,
            });
        }
        self.tracks = out;
    }

    /// Audio tracks subset, in mpv's own order.
    pub fn audio_tracks(&self) -> impl Iterator<Item = &TrackInfo> {
        self.tracks.iter().filter(|t| t.kind == "audio")
    }
}

impl PlayerState {
    /// Apply an mpv PROPERTY_CHANGE event: pull the new value out of the
    /// event payload using the format we registered with observe_property.
    pub unsafe fn apply_property_change(&mut self, ev: *const mp::mpv_event) { unsafe {
        let prop_ptr = (*ev).data as *const mp::mpv_event_property;
        if prop_ptr.is_null() {
            return;
        }
        let prop = &*prop_ptr;
        if prop.data.is_null() {
            return;
        }
        let id = (*ev).reply_userdata;
        match id {
            PROP_TIME_POS => {
                if prop.format == mp::MPV_FORMAT_DOUBLE {
                    self.time_pos = *(prop.data as *const f64);
                }
            }
            PROP_DURATION => {
                if prop.format == mp::MPV_FORMAT_DOUBLE {
                    self.duration = *(prop.data as *const f64);
                }
            }
            PROP_PAUSE => {
                if prop.format == mp::MPV_FORMAT_FLAG {
                    self.paused = *(prop.data as *const c_int) != 0;
                }
            }
            PROP_VOLUME => {
                if prop.format == mp::MPV_FORMAT_DOUBLE {
                    self.volume = *(prop.data as *const f64);
                }
            }
            PROP_PAUSED_FOR_CACHE => {
                if prop.format == mp::MPV_FORMAT_FLAG {
                    self.buffering = *(prop.data as *const c_int) != 0;
                }
            }
            PROP_FILENAME => {
                if prop.format == mp::MPV_FORMAT_STRING {
                    let s_ptr = *(prop.data as *const *const std::os::raw::c_char);
                    if !s_ptr.is_null() {
                        if let Ok(s) = CStr::from_ptr(s_ptr).to_str() {
                            self.filename = s.to_string();
                        }
                    }
                }
            }
            PROP_MUTE => {
                if prop.format == mp::MPV_FORMAT_FLAG {
                    self.muted = *(prop.data as *const c_int) != 0;
                }
            }
            PROP_SPEED => {
                if prop.format == mp::MPV_FORMAT_DOUBLE {
                    self.speed = *(prop.data as *const f64);
                }
            }
            PROP_SID => {
                if prop.format == mp::MPV_FORMAT_STRING {
                    let s_ptr = *(prop.data as *const *const std::os::raw::c_char);
                    self.current_sid = if s_ptr.is_null() {
                        None
                    } else {
                        CStr::from_ptr(s_ptr).to_str().ok().map(|s| s.to_string())
                    };
                }
            }
            PROP_AID => {
                if prop.format == mp::MPV_FORMAT_STRING {
                    let s_ptr = *(prop.data as *const *const std::os::raw::c_char);
                    self.current_aid = if s_ptr.is_null() {
                        None
                    } else {
                        CStr::from_ptr(s_ptr).to_str().ok().map(|s| s.to_string())
                    };
                }
            }
            PROP_EOF_REACHED => {
                // mpv 把 eof-reached 翻成 true → 当前文件自然播完。
                // keep-open=yes 让 mpv 不退出、不发 END_FILE，所以这是
                // 我们感知 EOF 的唯一可靠信号。注意 mpv 在 loadfile 加载
                // 新文件时也会先把 eof-reached 推一次 false，再切到具体
                // 状态——主循环只在 true 时才置 pending_auto_next，false
                // 推送忽略即可。
                if prop.format == mp::MPV_FORMAT_FLAG {
                    let v = *(prop.data as *const c_int) != 0;
                    if v {
                        self.pending_auto_next = true;
                    }
                }
            }
            _ => {}
        }
    }}
}

/// Subscribe to all the properties the HUD depends on. Call once after
/// mpv_initialize but before loadfile.
pub unsafe fn observe_default_properties(handle: *mut mp::mpv_handle) -> Result<(), String> {
    unsafe {
        for (id, name, format) in [
            (PROP_TIME_POS, "time-pos", mp::MPV_FORMAT_DOUBLE),
            (PROP_DURATION, "duration", mp::MPV_FORMAT_DOUBLE),
            (PROP_PAUSE, "pause", mp::MPV_FORMAT_FLAG),
            (PROP_VOLUME, "volume", mp::MPV_FORMAT_DOUBLE),
            (PROP_PAUSED_FOR_CACHE, "paused-for-cache", mp::MPV_FORMAT_FLAG),
            (PROP_FILENAME, "filename", mp::MPV_FORMAT_STRING),
            (PROP_MUTE, "mute", mp::MPV_FORMAT_FLAG),
            (PROP_SPEED, "speed", mp::MPV_FORMAT_DOUBLE),
            // sid/aid mpv 内部存的可能是数字或 "no"，直接拉字符串最稳。
            (PROP_SID, "sid", mp::MPV_FORMAT_STRING),
            (PROP_AID, "aid", mp::MPV_FORMAT_STRING),
            (PROP_EOF_REACHED, "eof-reached", mp::MPV_FORMAT_FLAG),
        ] {
            let cname = CString::new(name).unwrap();
            let r = mp::mpv_observe_property(handle, id, cname.as_ptr(), format);
            if r < 0 {
                return Err(format!("observe_property {name}: {}", mp::err_string(r)));
            }
        }
    }
    Ok(())
}

/// Actions the HUD wants the frame loop to perform on libmpv. We don't
/// call mpv_* from inside egui — rendering is a pure frame, side-effects
/// are queued and flushed once per loop iteration.
#[derive(Debug, Clone)]
pub enum Action {
    TogglePause,
    Seek(f64),
    SetVolume(f64),
    /// Toggle mpv `mute` property.
    ToggleMute,
    /// Set playback speed (0.5 .. 2.0). 1.0 = realtime.
    SetSpeed(f64),
    /// Pick a subtitle. `None` = turn subtitles off (mpv `set sid no`).
    /// `Some(url)` = `sub-add <url> select` so mpv loads the external
    /// file and switches to it. We pass URL rather than mpv's internal
    /// numeric sid because external sub ids shift around.
    SetSubtitle(Option<String>),
    /// Pick an embedded subtitle by mpv's `track-list[i].id`. Distinct
    /// from `SetSubtitle` because internal tracks already exist; we just
    /// flip `sid` rather than calling sub-add.
    SetSubtitleTrack(i64),
    /// Pick an audio track by mpv id (the integer in `track-list[i].id`).
    SetAudioTrack(i64),
    Quit,
    /// Switch to a different resource (episode / quality). The frame
    /// loop turns this into `loadfile` + remembered `time-pos` if the
    /// new file looks like the same content (M3.6 keeps this dumb —
    /// only switch the URL, no time preservation yet).
    SwitchResource { id: String, url: String },
    /// Toggle OS fullscreen on the Win32 window. The frame loop owns
    /// `PlayerWindow`, so it gets to do the SetWindowPlacement dance.
    ToggleFullscreen,
    /// User clicked a season tab in the right-side panel — switch the
    /// active season for the episode grid filter. The frame loop applies
    /// it back into PlayerState.active_season; mpv is untouched (no
    /// resource switch happens until the user actually picks an episode).
    SetSeason(i32),
    /// 打开「在线字幕搜索」面板。主循环把 PlayerState.online_search_open 翻 true，
    /// 默认用当前 movie title 作为关键词跑首次 search。
    OpenSubtitleSearch,
    /// 关闭搜索面板。
    CloseSubtitleSearch,
    /// 用新关键词重跑搜索 —— 触发 worker 线程异步拉取，结果回写 state。
    RunSubtitleSearch(String),
    /// 预览候选 —— download 字节 → 写临时文件 → mpv sub-add+select。不持久化。
    PreviewOnlineSubtitle { candidate_id: String, label: String },
    /// 绑定候选 —— bind (confirm=true) 持久化，把返回的 subtitle 注入
    /// state.movie.resources 当前条目，跟初始外挂字幕走同一路径。
    BindOnlineSubtitle { candidate_id: String, label: String },
    /// 用户点「✕」请求删除一条已绑定字幕：UI 进入二次确认态，把行内按钮
    /// 换成「确定 / 取消」。subtitle_id 是 SubtitleMeta.id（即后端
    /// playback.subtitles.items[].id）。
    RequestDeleteSubtitle(String),
    /// 用户在二次确认态点「确定」：spawn DELETE worker，worker 完成后
    /// 主循环把这条 subtitle 从 state.movie.resources 里摘掉、并通知 mpv
    /// sub-remove。
    ConfirmDeleteSubtitle(String),
    /// 用户在二次确认态点「取消」或者点了别处 —— 把 pending_delete_sid
    /// 清回 None。
    CancelDeleteSubtitle,
}

impl Action {
    pub unsafe fn apply(&self, handle: *mut mp::mpv_handle) {
        unsafe {
            match self {
                Action::TogglePause => {
                    let cmd = [c"cycle".as_ptr(), c"pause".as_ptr(), ptr::null()];
                    mp::mpv_command(handle, cmd.as_ptr() as *mut _);
                }
                Action::Seek(t) => {
                    let mut v = *t;
                    let name = c"time-pos";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_DOUBLE,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetVolume(v) => {
                    let mut v = *v;
                    let name = c"volume";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_DOUBLE,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::ToggleMute => {
                    // `cycle mute` 翻转布尔；mpv 自己处理 yes/no 的字符串细节。
                    let cmd = [c"cycle".as_ptr(), c"mute".as_ptr(), ptr::null()];
                    mp::mpv_command(handle, cmd.as_ptr() as *mut _);
                }
                Action::SetSpeed(s) => {
                    let mut v = *s;
                    let name = c"speed";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_DOUBLE,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetSubtitle(opt) => {
                    match opt {
                        None => {
                            // 关闭字幕：mpv 把 sid 设成 "no"。
                            let name = c"sid";
                            let val = c"no";
                            mp::mpv_set_property_string(handle, name.as_ptr(), val.as_ptr());
                        }
                        Some(url) => {
                            // sub-add 第三个参数 "select" 让 mpv 加载完外部
                            // 字幕后立即切到它，免去我们手动算新 sid。
                            let curl = std::ffi::CString::new(url.as_str())
                                .unwrap_or_default();
                            let cmd = [
                                c"sub-add".as_ptr(),
                                curl.as_ptr(),
                                c"select".as_ptr(),
                                ptr::null(),
                            ];
                            mp::mpv_command(handle, cmd.as_ptr() as *mut _);
                        }
                    }
                }
                Action::SetSubtitleTrack(id) => {
                    // 内嵌字幕：直接 set sid <number>。
                    let s = id.to_string();
                    let cval = std::ffi::CString::new(s).unwrap_or_default();
                    let name = c"sid";
                    mp::mpv_set_property_string(handle, name.as_ptr(), cval.as_ptr());
                }
                Action::SetAudioTrack(id) => {
                    // aid 是字符串 "1"/"2"/.../"no"；mpv_set_property_string
                    // 是最稳妥的 setter（不用纠结整型 typing）。
                    let s = id.to_string();
                    let cval = std::ffi::CString::new(s).unwrap_or_default();
                    let name = c"aid";
                    mp::mpv_set_property_string(handle, name.as_ptr(), cval.as_ptr());
                }
                Action::Quit => {
                    let cmd = [c"quit".as_ptr(), ptr::null()];
                    mp::mpv_command(handle, cmd.as_ptr() as *mut _);
                }
                Action::SwitchResource { url, .. } => {
                    // 切源/切集：mpv 之前为了"续播"设过 start=<seconds>，这个
                    // 选项作用于"下一次 loadfile"，没人主动清——会污染换集。
                    // 用户反馈："切集后进度条带着上一集的位置开始"。先把
                    // start option 设回 "none"（mpv 文档：start=none 表示
                    // 从头），再 loadfile 才能保证新一集回到 0。
                    let opt_name = c"start";
                    let opt_val = c"none";
                    mp::mpv_set_option_string(
                        handle,
                        opt_name.as_ptr(),
                        opt_val.as_ptr(),
                    );
                    let curl = std::ffi::CString::new(url.as_str()).unwrap_or_default();
                    let cmd = [
                        c"loadfile".as_ptr(),
                        curl.as_ptr(),
                        ptr::null(),
                    ];
                    mp::mpv_command(handle, cmd.as_ptr() as *mut _);
                }
                // 全屏切换是 Win32 窗口层的事情，需要拿到 PlayerWindow，
                // 由主循环处理（见 mod.rs 的 dispatch）；这里 noop。
                Action::ToggleFullscreen => {}
                // 切季 tab 只更新 PlayerState.active_season，不动 mpv。
                // 同样在主循环里直接读取后写状态。
                Action::SetSeason(_) => {}
                // 在线字幕相关：所有动作都在 mod.rs 主循环里处理（开/关面板、
                // 触发 worker 线程、拼装临时文件路径等）。这里全 noop。
                Action::OpenSubtitleSearch
                | Action::CloseSubtitleSearch
                | Action::RunSubtitleSearch(_)
                | Action::PreviewOnlineSubtitle { .. }
                | Action::BindOnlineSubtitle { .. }
                | Action::RequestDeleteSubtitle(_)
                | Action::ConfirmDeleteSubtitle(_)
                | Action::CancelDeleteSubtitle => {}
            }
        }
    }
}
