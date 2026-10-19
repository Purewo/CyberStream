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
pub const PROP_SUB_DELAY: u64 = 12;
pub const PROP_AUDIO_DELAY: u64 = 13;
pub const PROP_SUB_FONT_SIZE: u64 = 14;
pub const PROP_SUB_POS: u64 = 15;
pub const PROP_SUB_COLOR: u64 = 16;
pub const PROP_ASS_OVERRIDE: u64 = 17;
pub const PROP_BRIGHTNESS: u64 = 18;
pub const PROP_CONTRAST: u64 = 19;
pub const PROP_SATURATION: u64 = 20;
pub const PROP_GAMMA: u64 = 21;
pub const PROP_ASPECT: u64 = 22;
pub const PROP_AB_A: u64 = 23;
pub const PROP_AB_B: u64 = 24;
pub const PROP_SUB_SCALE: u64 = 25;
pub const PROP_SUB_BORDER_SIZE: u64 = 26;
pub const PROP_SUB_BACK_COLOR: u64 = 27;
pub const PROP_SUB_BORDER_STYLE: u64 = 28;

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
    /// 当前选中的云转码画质 URL（仅夸克/UC 资源有意义）。HUD 清晰度菜单
    /// 按这个值判定哪一档高亮；切档时主循环更新它。None = 非云转码资源或
    /// 尚未选档。启动时若 current_resource 有 qualities，填默认档 url。
    pub current_quality_url: Option<String>,
    /// 选集网格的当前分段页（每段 30 集，与 web 端一致）。集数多时网格按
    /// 1-30 / 31-60 ... 分段，这里记当前看的是第几段（0 基）。播放集变化时
    /// 主循环/UI 会把它对齐到当前集所在段。
    pub episode_page: usize,
    /// 最近一次 mpv 加载失败的提示文案。None = 无错误（正常）。drain_mpv_events
    /// 收到 END_FILE(reason=ERROR) 时填（401/404/断网等），HUD 画失败横幅；
    /// 下一次成功 loadfile(START_FILE / 正常 EOF) 时清空。代托管模式下 mpv 拿
    /// 不到 cookie 导致 /stream 401 是最高频来源——给用户可见反馈而非黑屏。
    pub last_error: Option<String>,
    /// 播放票据（代托管模式）。open_pc_player 启动时由前端传入并存这里，
    /// HUD 内发起的在线字幕 worker（online_subs 独立线程拿不到 cookie）拼到
    /// ?ticket=... 上过认证。None = 非代托管 / 未登录。
    pub playback_ticket: Option<String>,

    // ─────────── 设置面板运行时状态（mpv 实时调节，不持久化）───────────
    /// 字幕偏移秒数（mpv sub-delay）。0.0 默认即对。
    pub sub_delay: f64,
    /// 音频偏移秒数（mpv audio-delay）。0.0 默认即对。
    pub audio_delay: f64,
    /// 字幕字号（mpv sub-font-size）。⚠默认 55，须 mod.rs 初始化（Default 给 0 是错的）。
    pub sub_font_size: f64,
    /// Text subtitle scale, outline and background are observed from mpv.
    pub sub_scale: f64,
    pub sub_border_size: f64,
    pub sub_back_color: String,
    pub sub_border_style: String,
    /// 字幕垂直位置（mpv sub-pos）。⚠默认 100，须 mod.rs 初始化。
    pub sub_pos: i64,
    /// 字幕颜色 "#RRGGBB"（mpv sub-color）。⚠默认 "#FFFFFF"，须 mod.rs 初始化。
    pub sub_color: String,
    /// 是否强制覆盖 ASS 样式（mpv sub-ass-override=force）。false 默认即对。
    pub force_ass_override: bool,
    /// 画面亮度/对比度/饱和度/gamma（mpv 同名属性）。0 默认即对。
    pub brightness: i64,
    pub contrast: i64,
    pub saturation: i64,
    pub gamma: i64,
    /// 当前画面比例覆盖。None=原始(video-aspect-override=-1)，Some("16:9")等=强制。
    pub current_aspect: Option<String>,
    /// A-B 复读 A/B 点秒数。None=未设。
    pub ab_loop_a: Option<f64>,
    pub ab_loop_b: Option<f64>,
    /// 睡眠定时器截止时刻（单调钟 Instant，非 SystemTime 防系统时钟跳变）。None=未启用。
    pub sleep_deadline: Option<std::time::Instant>,
    /// 睡眠定时器到点动作。
    pub sleep_kind: SleepKind,
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
    /// 下载次数（人气）。后端 download_number，多为字符串如 "1.2万"。
    pub download_number: Option<String>,
    /// 上传者。
    pub uploader: Option<String>,
    /// 评分 / 质量标记。
    pub rating: Option<String>,
    /// 文件大小（后端已格式化字符串，如 "24.5 KB"）。
    pub file_size: Option<String>,
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
    /// 以下仅对音轨/视频轨有意义——mpv `track-list` 在轨道有 demux 元数据时回填。
    /// 比如 PotPlayer 那种"7.1 Ch · 48.0 kHz · 1.51 Mbps"细节，菜单上挑轨更直观。
    pub audio_channels: Option<i64>,
    pub samplerate: Option<i64>,
    pub bitrate: Option<i64>,
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
            // demux 元数据：仅在 mpv 解出来时有；外挂字幕一般没有这些。
            let audio_channels = item
                .get("audio-channels")
                .and_then(|v| v.as_i64());
            let samplerate = item
                .get("demux-samplerate")
                .and_then(|v| v.as_i64());
            let bitrate = item
                .get("demux-bitrate")
                .and_then(|v| v.as_i64());
            out.push(TrackInfo {
                id,
                kind,
                selected,
                title,
                lang,
                codec,
                external,
                external_filename,
                audio_channels,
                samplerate,
                bitrate,
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
            PROP_SUB_DELAY | PROP_AUDIO_DELAY | PROP_SUB_FONT_SIZE | PROP_ASPECT
                | PROP_SUB_SCALE | PROP_SUB_BORDER_SIZE => {
                if prop.format == mp::MPV_FORMAT_DOUBLE {
                    let value = *(prop.data as *const f64);
                    if value.is_finite() {
                        match id {
                            PROP_SUB_DELAY => self.sub_delay = value,
                            PROP_AUDIO_DELAY => self.audio_delay = value,
                            PROP_SUB_FONT_SIZE => self.sub_font_size = value,
                            PROP_SUB_SCALE => self.sub_scale = value,
                            PROP_SUB_BORDER_SIZE => self.sub_border_size = value,
                            PROP_ASPECT => self.current_aspect = aspect_label(value),
                            _ => {}
                        }
                    }
                }
            }
            PROP_SUB_POS | PROP_BRIGHTNESS | PROP_CONTRAST | PROP_SATURATION | PROP_GAMMA => {
                if prop.format == mp::MPV_FORMAT_INT64 {
                    let value = *(prop.data as *const i64);
                    match id {
                        PROP_SUB_POS => self.sub_pos = value,
                        PROP_BRIGHTNESS => self.brightness = value,
                        PROP_CONTRAST => self.contrast = value,
                        PROP_SATURATION => self.saturation = value,
                        PROP_GAMMA => self.gamma = value,
                        _ => {}
                    }
                }
            }
            PROP_SUB_COLOR | PROP_ASS_OVERRIDE | PROP_AB_A | PROP_AB_B | PROP_SUB_BACK_COLOR | PROP_SUB_BORDER_STYLE => {
                if prop.format == mp::MPV_FORMAT_STRING {
                    let raw = *(prop.data as *const *const std::os::raw::c_char);
                    if !raw.is_null() {
                        let value = CStr::from_ptr(raw).to_string_lossy();
                        match id {
                            PROP_SUB_COLOR => {
                                self.sub_color = if value.len() == 9 && value.get(..3).is_some_and(|s| s.eq_ignore_ascii_case("#ff")) {
                                    format!("#{}", &value[3..])
                                } else { value.into_owned() };
                            }
                            PROP_ASS_OVERRIDE => self.force_ass_override = value == "force",
                            PROP_SUB_BACK_COLOR => self.sub_back_color = value.into_owned(),
                            PROP_SUB_BORDER_STYLE => self.sub_border_style = value.into_owned(),
                            PROP_AB_A => self.ab_loop_a = value.parse::<f64>().ok().filter(|v| v.is_finite()),
                            PROP_AB_B => self.ab_loop_b = value.parse::<f64>().ok().filter(|v| v.is_finite()),
                            _ => {}
                        }
                    }
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

fn aspect_label(value: f64) -> Option<String> {
    if value <= 0.0 { return None; }
    for (ratio, label) in [(16.0 / 9.0, "16:9"), (4.0 / 3.0, "4:3"), (1.85, "1.85"), (2.35, "2.35")] {
        if (value - ratio).abs() < 0.0001 { return Some(label.to_string()); }
    }
    Some(value.to_string())
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
            (PROP_SUB_DELAY, "sub-delay", mp::MPV_FORMAT_DOUBLE),
            (PROP_AUDIO_DELAY, "audio-delay", mp::MPV_FORMAT_DOUBLE),
            (PROP_SUB_FONT_SIZE, "sub-font-size", mp::MPV_FORMAT_DOUBLE),
            (PROP_SUB_POS, "sub-pos", mp::MPV_FORMAT_INT64),
            (PROP_SUB_COLOR, "sub-color", mp::MPV_FORMAT_STRING),
            (PROP_ASS_OVERRIDE, "sub-ass-override", mp::MPV_FORMAT_STRING),
            (PROP_BRIGHTNESS, "brightness", mp::MPV_FORMAT_INT64),
            (PROP_CONTRAST, "contrast", mp::MPV_FORMAT_INT64),
            (PROP_SATURATION, "saturation", mp::MPV_FORMAT_INT64),
            (PROP_GAMMA, "gamma", mp::MPV_FORMAT_INT64),
            (PROP_ASPECT, "video-aspect-override", mp::MPV_FORMAT_DOUBLE),
            (PROP_AB_A, "ab-loop-a", mp::MPV_FORMAT_STRING),
            (PROP_AB_B, "ab-loop-b", mp::MPV_FORMAT_STRING),
            (PROP_SUB_SCALE, "sub-scale", mp::MPV_FORMAT_DOUBLE),
            // Observe the canonical option: the legacy alias misses later updates.
            (PROP_SUB_BORDER_SIZE, "sub-outline-size", mp::MPV_FORMAT_DOUBLE),
            (PROP_SUB_BACK_COLOR, "sub-back-color", mp::MPV_FORMAT_STRING),
            (PROP_SUB_BORDER_STYLE, "sub-border-style", mp::MPV_FORMAT_STRING),
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
    /// 切清晰度：同一资源换云转码档位 URL，**保留当前播放进度**（区别于
    /// SwitchResource 的从头播放）。url 是该档位的 stream-transcoded 绝对地址。
    /// 实际 loadfile 在 mod.rs 主循环处理——要读 state.time_pos 决定 start，
    /// apply() 拿不到 state，所以这里只是个信号，apply() 内 noop。
    SwitchQuality { url: String },
    /// Toggle OS fullscreen on the Win32 window. The frame loop owns
    /// `PlayerWindow`, so it gets to do the SetWindowPlacement dance.
    ToggleFullscreen,
    /// User clicked a season tab in the right-side panel — switch the
    /// active season for the episode grid filter. The frame loop applies
    /// it back into PlayerState.active_season; mpv is untouched (no
    /// resource switch happens until the user actually picks an episode).
    SetSeason(i32),
    /// 切选集网格分段页（每段 30 集）。只改 PlayerState.episode_page，不动
    /// mpv——纯 UI 翻页，用户在 1-30 / 31-60 之间切换查看。
    SetEpisodePage(usize),
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

    // ─────────── 设置面板（mpv 原生能力，纯前端，不碰后端）───────────
    /// 字幕时间偏移（秒）。mpv `sub-delay`，正=字幕延后。apply() 直接设属性。
    SetSubDelay(f64),
    /// 音频时间偏移（秒）。mpv `audio-delay`，正=音频延后。
    SetAudioDelay(f64),
    /// 字幕字号。mpv `sub-font-size`（DOUBLE），默认 55。仅文本字幕生效，
    /// ASS 需配合 sub-ass-override=force；图形字幕无效（UI 层 gating）。
    SetSubFontSize(f64),
    SetSubScale(f64),
    SetSubBorderSize(f64),
    SetSubBackColor(String),
    SetSubBorderStyle(String),
    /// 字幕垂直位置。mpv `sub-pos`（INT64，0=顶 100=默认 150=底）。
    SetSubPos(i64),
    /// 字幕颜色。mpv `sub-color`，"#RRGGBB"。
    SetSubColor(String),
    /// 强制覆盖 ASS 自带样式。mpv `sub-ass-override`：true→"force" / false→"scale"。
    SetForceAssOverride(bool),
    /// 画面亮度。mpv `brightness`（INT64，-100..100）。
    SetBrightness(i64),
    /// 画面对比度。mpv `contrast`（INT64，-100..100）。
    SetContrast(i64),
    /// 画面饱和度。mpv `saturation`（INT64，-100..100）。
    SetSaturation(i64),
    /// 画面 gamma。mpv `gamma`（INT64，-100..100）。
    SetGamma(i64),
    /// 画面比例。mpv `video-aspect-override`："16:9"/"4:3"/"1.85"/"2.35"，"-1"=原始。
    SetAspect(String),
    /// A-B 复读·设 A 点。取当前 time_pos→mpv `ab-loop-a`。读 state，mod.rs 处理。
    SetAbLoopA,
    /// A-B 复读·设 B 点。取当前 time_pos→mpv `ab-loop-b`。读 state，mod.rs 处理。
    SetAbLoopB,
    /// A-B 复读·清除。mpv ab-loop-a/b = "no"。mod.rs 处理。
    ClearAbLoop,
    /// 截图（含字幕、不含 OSD）。mpv `screenshot subtitles`。涉及磁盘编码 IO，
    /// mod.rs 走 dispatch_mpv_command_async，apply() noop。
    Screenshot,
    /// 睡眠定时器：N 分钟后暂停或退出。app 层计时（mod.rs 每帧 tick），apply() noop。
    SetSleepTimer { minutes: u64, kind: SleepKind },
    /// 取消睡眠定时器。
    CancelSleepTimer,
}

/// 睡眠定时器到点动作。Pause=暂停播放（默认）；Quit=关闭播放器窗口。
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum SleepKind {
    #[default]
    Pause,
    Quit,
}

impl Action {
    /// UI state comes from mpv's observers, including normalized values and
    /// settings changed outside the HUD. The caller checks the setter result.
    pub fn setting_property(&self) -> Option<(&'static str, String)> {
        Some(match self {
            Self::SetSubDelay(v) => ("sub-delay", v.to_string()),
            Self::SetAudioDelay(v) => ("audio-delay", v.to_string()),
            Self::SetSubFontSize(v) => ("sub-font-size", v.to_string()),
            Self::SetSubScale(v) => ("sub-scale", v.clamp(0.3, 3.0).to_string()),
            Self::SetSubBorderSize(v) => ("sub-outline-size", v.clamp(0.0, 10.0).to_string()),
            Self::SetSubBackColor(v) => ("sub-back-color", v.clone()),
            Self::SetSubBorderStyle(v) => ("sub-border-style", v.clone()),
            Self::SetSubPos(v) => ("sub-pos", v.to_string()),
            Self::SetSubColor(v) => ("sub-color", v.clone()),
            Self::SetForceAssOverride(v) => ("sub-ass-override", if *v { "force" } else { "scale" }.into()),
            Self::SetBrightness(v) => ("brightness", v.to_string()),
            Self::SetContrast(v) => ("contrast", v.to_string()),
            Self::SetSaturation(v) => ("saturation", v.to_string()),
            Self::SetGamma(v) => ("gamma", v.to_string()),
            Self::SetAspect(v) => ("video-aspect-override", v.clone()),
            _ => return None,
        })
    }
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
                // 选集分段翻页只改 PlayerState.episode_page，主循环处理。
                Action::SetEpisodePage(_) => {}
                // 切清晰度要读 state.time_pos 决定 start=<pos>，apply 拿不到
                // state；实际 loadfile 在 mod.rs 主循环处理。这里 noop。
                Action::SwitchQuality { .. } => {}
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

                // ─────────── 设置面板 · DOUBLE 数值属性（仿 SetSpeed）───────────
                Action::SetSubDelay(d) => {
                    let mut v = *d;
                    let name = c"sub-delay";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_DOUBLE,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetAudioDelay(d) => {
                    let mut v = *d;
                    let name = c"audio-delay";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_DOUBLE,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetSubFontSize(n) => {
                    let mut v = *n;
                    let name = c"sub-font-size";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_DOUBLE,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                // ─────────── 设置面板 · INT64 数值属性 ───────────
                Action::SetSubPos(p) => {
                    let mut v: i64 = *p;
                    let name = c"sub-pos";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_INT64,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetBrightness(n) => {
                    let mut v: i64 = *n;
                    let name = c"brightness";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_INT64,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetContrast(n) => {
                    let mut v: i64 = *n;
                    let name = c"contrast";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_INT64,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetSaturation(n) => {
                    let mut v: i64 = *n;
                    let name = c"saturation";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_INT64,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                Action::SetGamma(n) => {
                    let mut v: i64 = *n;
                    let name = c"gamma";
                    mp::mpv_set_property(
                        handle,
                        name.as_ptr(),
                        mp::MPV_FORMAT_INT64,
                        &mut v as *mut _ as *mut c_void,
                    );
                }
                // ─────────── 设置面板 · 字符串属性 ───────────
                Action::SetSubScale(_) | Action::SetSubBorderSize(_) | Action::SetSubBackColor(_) | Action::SetSubBorderStyle(_) => {
                    if let Some((name, value)) = self.setting_property() {
                        if let (Ok(name), Ok(value)) = (CString::new(name), CString::new(value)) {
                            mp::mpv_set_property_string(handle, name.as_ptr(), value.as_ptr());
                        }
                    }
                }
                Action::SetSubColor(s) => {
                    if let Ok(cval) = CString::new(s.as_str()) {
                        mp::mpv_set_property_string(handle, c"sub-color".as_ptr(), cval.as_ptr());
                    }
                }
                Action::SetForceAssOverride(on) => {
                    let mode = if *on { c"force" } else { c"scale" };
                    mp::mpv_set_property_string(
                        handle,
                        c"sub-ass-override".as_ptr(),
                        mode.as_ptr(),
                    );
                }
                Action::SetAspect(a) => {
                    if let Ok(cval) = CString::new(a.as_str()) {
                        mp::mpv_set_property_string(
                            handle,
                            c"video-aspect-override".as_ptr(),
                            cval.as_ptr(),
                        );
                    }
                }
                // A-B 复读读 state.time_pos，apply 拿不到 state；mod.rs 主循环处理。
                Action::SetAbLoopA | Action::SetAbLoopB | Action::ClearAbLoop => {}
                // 截图涉及磁盘编码 IO，mod.rs 走 dispatch_mpv_command_async。
                Action::Screenshot => {}
                // 睡眠定时器是 app 层计时，mod.rs 写 state + 每帧 tick。
                Action::SetSleepTimer { .. } | Action::CancelSleepTimer => {}
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::native_player::render::MpvPlayer;

    fn pump_until(player: &MpvPlayer, state: &mut PlayerState, ready: impl Fn(&PlayerState) -> bool) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
        while !ready(state) && std::time::Instant::now() < deadline {
            unsafe {
                let event = mp::mpv_wait_event(player.handle(), 0.02);
                if !event.is_null() && (*event).event_id == mp::MPV_EVENT_PROPERTY_CHANGE {
                    state.apply_property_change(event);
                }
            }
        }
        assert!(ready(state), "settings observer did not report the actual values: {state:?}");
    }

    #[test]
    fn settings_observers_follow_actual_values_and_reject_failed_updates() {
        let player = unsafe { MpvPlayer::create() }.unwrap();
        player.set_property_str("sub-font-size", "38").unwrap();
        unsafe { observe_default_properties(player.handle()).unwrap(); }
        let mut state = PlayerState::default();
        pump_until(&player, &mut state, |s| s.sub_font_size == 38.0 && s.sub_pos == 100);
        for action in [
            Action::SetBrightness(14), Action::SetContrast(-19), Action::SetSaturation(33),
            Action::SetGamma(7), Action::SetSubDelay(1.2), Action::SetAudioDelay(-0.4),
            Action::SetSubFontSize(46.0), Action::SetSubPos(90),
            Action::SetSubColor("#FF0000".into()), Action::SetForceAssOverride(true),
            Action::SetAspect("16:9".into()),
        ] {
            let (name, value) = action.setting_property().unwrap();
            player.set_property_str(name, &value).unwrap();
        }
        player.set_property_str("ab-loop-a", "4.5").unwrap();
        player.set_property_str("ab-loop-b", "8.5").unwrap();
        pump_until(&player, &mut state, |s| s.brightness == 14 && s.contrast == -19
            && s.saturation == 33 && s.gamma == 7 && (s.sub_delay - 1.2).abs() < 0.0001 && (s.audio_delay + 0.4).abs() < 0.0001
            && s.sub_font_size == 46.0 && s.sub_pos == 90 && s.sub_color == "#FF0000"
            && s.force_ass_override && s.current_aspect.as_deref() == Some("16:9")
            && s.ab_loop_a == Some(4.5) && s.ab_loop_b == Some(8.5));
        assert!(player.set_property_str("sub-color", "invalid-color").is_err());
        assert_eq!(state.sub_color, "#FF0000");
        player.set_property_str("ab-loop-a", "no").unwrap();
        player.set_property_str("ab-loop-b", "no").unwrap();
        player.set_property_str("video-aspect-override", "-1").unwrap();
        pump_until(&player, &mut state, |s| s.ab_loop_a.is_none() && s.ab_loop_b.is_none() && s.current_aspect.is_none());
    }

    #[test]
    fn subtitle_button_controls_follow_real_mpv_state() {
        let player = unsafe { MpvPlayer::create() }.unwrap();
        unsafe { observe_default_properties(player.handle()).unwrap(); }
        let mut state = PlayerState::default();
        pump_until(&player, &mut state, |s| s.sub_scale > 0.0 && s.sub_border_size > 0.0 && !s.sub_back_color.is_empty());
        for action in [Action::SetSubScale(1.1), Action::SetSubBorderSize(3.5), Action::SetSubBackColor("#80000000".into()), Action::SetSubBorderStyle("background-box".into())] {
            let (name, value) = action.setting_property().unwrap();
            player.set_property_str(name, &value).unwrap();
        }
        pump_until(&player, &mut state, |s| (s.sub_scale - 1.1).abs() < 0.0001
            && s.sub_border_size == 3.5 && s.sub_back_color == "#80000000" && s.sub_border_style == "background-box");
        for action in [Action::SetSubScale(1.0), Action::SetSubBorderSize(-1.0), Action::SetSubBackColor("#00000000".into()), Action::SetSubBorderStyle("outline-and-shadow".into())] {
            let (name, value) = action.setting_property().unwrap();
            player.set_property_str(name, &value).unwrap();
        }
        pump_until(&player, &mut state, |s| s.sub_scale == 1.0 && s.sub_border_size == 0.0 && s.sub_back_color == "#00000000" && s.sub_border_style == "outline-and-shadow");
        assert_eq!(Action::SetSubScale(9.0).setting_property().unwrap().1, "3");
    }

    #[test]
    fn settings_actions_update_real_libmpv_properties() {
        let player = unsafe { MpvPlayer::create() }.expect("installed libmpv initializes");
        for (action, name, expected) in [
            (Action::SetBrightness(24), "brightness", 24.0),
            (Action::SetContrast(-17), "contrast", -17.0),
            (Action::SetSaturation(31), "saturation", 31.0),
            (Action::SetGamma(8), "gamma", 8.0),
            (Action::SetSubDelay(1.4), "sub-delay", 1.4),
            (Action::SetAudioDelay(-0.7), "audio-delay", -0.7),
            (Action::SetSubFontSize(42.0), "sub-font-size", 42.0),
            (Action::SetSubPos(90), "sub-pos", 90.0),
            (Action::SetSpeed(1.5), "speed", 1.5),
        ] {
            unsafe { action.apply(player.handle()); }
            let actual = player.get_property_string(name).unwrap().parse::<f64>().unwrap();
            assert!((actual - expected).abs() < 0.001, "{name}: {actual} != {expected}");
        }
        unsafe { Action::SetForceAssOverride(true).apply(player.handle()); }
        assert_eq!(player.get_property_string("sub-ass-override").as_deref(), Some("force"));
        unsafe { Action::SetForceAssOverride(false).apply(player.handle()); }
        assert_eq!(player.get_property_string("sub-ass-override").as_deref(), Some("scale"));
        unsafe { Action::SetSubColor("#FF0000".into()).apply(player.handle()); }
        assert_eq!(player.get_property_string("sub-color").as_deref(), Some("#FFFF0000"));
    }
}
