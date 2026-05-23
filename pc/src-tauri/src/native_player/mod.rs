// CyberStream PC · native player module
//
// v3 architecture: libmpv + OpenGL render API + a separate windowed
// Win32 window owned by this module. See plan v3 §4.
//
// M3.2 deliverable: video frame from libmpv + egui HUD (top bar with
// title/back, bottom bar with progress/transport/volume) painted in
// the same default framebuffer.

pub mod controller;
pub mod ffi;
pub mod heartbeat;
pub mod meta;
pub mod online_subs;
pub mod render;
pub mod ui;
pub mod window;

use std::time::{Duration, Instant};

use glow::HasContext;

use crate::native_player::controller::{observe_default_properties, PlayerState};
use crate::native_player::ffi as mp;
use crate::native_player::heartbeat::{spawn as spawn_heartbeat, ProgressSnapshot};
use crate::native_player::meta::MovieMeta;
use crate::native_player::render::MpvPlayer;
use crate::native_player::ui::Hud;
use crate::native_player::window::{InputEvent, KeyCode, MouseButton, PlayerWindow};

/// Drive the player end-to-end: window + GL context, libmpv handle +
/// render context, egui HUD, frame loop, input forwarding.
pub fn run_player_blocking(opts: PlayOptions) -> Result<(), String> {
    unsafe {
        let win = PlayerWindow::create()
            .map_err(|e| format!("PlayerWindow::create: {e}"))?;

        let mut player = MpvPlayer::create()?;
        player.init_render()?;
        observe_default_properties(player.handle())?;

        // Headers (Authorization, Cookie, ...) the webview already
        // negotiated with the backend. mpv accepts a `\r\n`-joined
        // string via the `http-header-fields` option.
        if !opts.headers.is_empty() {
            let joined = opts
                .headers
                .iter()
                .map(|(k, v)| format!("{k}: {v}"))
                .collect::<Vec<_>>()
                .join("\r\n");
            player.set_option("http-header-fields", &joined)?;
        }

        // Resume position: mpv applies `start=<seconds>` only to the
        // next loadfile, so set it before the command below.
        if opts.start_time > 0.5 {
            player.set_option("start", &format!("{:.3}", opts.start_time))?;
        }

        // 视频流代理：从 proxy::video_proxy_url 取，独立于 app_proxy。mpv 的
        // `http-proxy` option 跟 curl 一样接 http(s):// 或 socks5://；用户没配
        // 时显式塞空串覆盖 mpv 默认（会读 HTTP_PROXY 环境变量），跟 WebView2
        // / reqwest 那边的"无配置即直连"行为对齐——避免 v2rayN 等系统代理把
        // 视频流偷偷拽走。
        let vp = crate::proxy::video_proxy_url().unwrap_or_default();
        player.set_option("http-proxy", &vp)?;

        let mut hud = Hud::new()?;
        let mut state = PlayerState::default();
        // 把前端送过来的元数据塞到 state 里，HUD 右侧面板会读这些字段。
        state.movie = opts.movie.clone();
        state.current_resource_id = opts.current_resource_id.clone();
        // mpv 默认 speed=1.0；不等 PROP_SPEED 触发了，先填上避免 HUD 倍速
        // 下拉第一帧显示「0.0x」。
        state.speed = 1.0;

        // 启动心跳线程：webview 给了 device_id + api_base 才发，否则跳过
        // （比如 Rust 直接 cargo run 跑 PoC 时 PlayOptions 是空的）。
        let heartbeat = if !opts.device_id.is_empty() && !opts.api_base.is_empty() {
            let session = opts
                .session_id
                .clone()
                .unwrap_or_else(|| format!("pc-{}", uuid::Uuid::new_v4()));
            let initial = ProgressSnapshot {
                resource_id: state
                    .current_resource_id
                    .clone()
                    .unwrap_or_default(),
                position_sec: opts.start_time,
                duration_sec: 0.0,
            };
            Some(spawn_heartbeat(
                opts.api_base.clone(),
                opts.device_id.clone(),
                "CyberStream PC (Native Player)".into(),
                session,
                initial,
            ))
        } else {
            None
        };

        // Kick off playback.
        player.command(&["loadfile", &opts.url])?;

        let mut last_event_drain = Instant::now();
        let mut last_mouse_pos = (0.0_f32, 0.0_f32);
        // 当前修饰键状态。每帧从 GetAsyncKeyState 拉，避免错过任何 keyup
        // / 焦点切换导致的"卡住按下态"。同时拷贝给 egui，用来识别 Ctrl+A/
        // Ctrl+C/Shift+方向键之类的组合键。
        let mut current_modifiers = egui::Modifiers::default();
        // Cache last-applied mpv video margins so we only push updates
        // when they actually change (avoids spamming mpv every frame).
        let mut last_margin_bottom = -1.0_f64;
        let mut last_margin_right = -1.0_f64;
        // 在线字幕 worker → 主循环的回调通道（预览/绑定结果）。worker 完成后
        // 把结果送进来，下一帧主循环 try_recv 拿到再走 mpv sub-add / 注入
        // state.movie。无界 channel 即可——一次最多就两三条结果，不存在
        // backpressure 担忧；用 sync_channel 反而增加 sender/receiver 类型耦合。
        let (preview_tx, preview_rx) =
            std::sync::mpsc::channel::<crate::native_player::online_subs::PreviewReady>();
        let (bind_tx, bind_rx) =
            std::sync::mpsc::channel::<crate::native_player::online_subs::BindReady>();
        let (delete_tx, delete_rx) =
            std::sync::mpsc::channel::<crate::native_player::online_subs::DeleteReady>();
        // track-list 每秒拉一次 — 不在 observe_property 里走是因为 NODE
        // 格式解码代码量大、字符串 + serde_json 已经够用且更宽容。
        let mut last_track_pull = Instant::now()
            .checked_sub(Duration::from_secs(60))
            .unwrap_or_else(Instant::now);
        let mut last_heartbeat_push = Instant::now();

        loop {
            if !win.pump_messages() {
                break;
            }

            // Drain mpv events ~60 Hz, applying property changes to state.
            if last_event_drain.elapsed() > Duration::from_millis(16) {
                if drain_mpv_events(&player, &mut state) {
                    break;
                }
                last_event_drain = Instant::now();
            }

            // Forward Win32 input to egui.
            // 双击事件需要单独处理：egui 自身并没有"双击切全屏"概念，所以
            // 我们先攒到 pending_double_click，等知道实际客户端尺寸 + 哪些
            // 区域被 HUD 占用时再决定是不是触发 ToggleFullscreen。
            let mut pending_double_click: Option<(f32, f32)> = None;
            for ev in win.drain_events() {
                match ev {
                    InputEvent::MouseMove { x, y } => {
                        last_mouse_pos = (x, y);
                        hud.push_event(egui::Event::PointerMoved(egui::pos2(x, y)));
                    }
                    InputEvent::MouseButton { button, pressed, x, y } => {
                        let egui_btn = match button {
                            MouseButton::Left => egui::PointerButton::Primary,
                            MouseButton::Right => egui::PointerButton::Secondary,
                            MouseButton::Middle => egui::PointerButton::Middle,
                        };
                        last_mouse_pos = (x, y);
                        hud.push_event(egui::Event::PointerButton {
                            pos: egui::pos2(x, y),
                            button: egui_btn,
                            pressed,
                            modifiers: egui::Modifiers::default(),
                        });
                    }
                    InputEvent::MouseDoubleClick { x, y } => {
                        // 只记最后一次；同一帧多次双击没意义。
                        pending_double_click = Some((x, y));
                    }
                    InputEvent::MouseWheel { delta } => {
                        hud.push_event(egui::Event::MouseWheel {
                            unit: egui::MouseWheelUnit::Line,
                            delta: egui::vec2(0.0, delta),
                            modifiers: egui::Modifiers::default(),
                        });
                    }
                    InputEvent::Key { code, pressed } => {
                        // 全局快捷键（PotPlayer 风格）只在 keydown 上触发，
                        // keyup 仍要透传给 egui，否则它的内部按键状态会卡住。
                        //   - Esc：全屏时退出全屏；非全屏时关闭播放器
                        //   - Enter：进入全屏（已经全屏则当 noop，不再切回）
                        //   - Space：播放 / 暂停
                        // 这些键不再 push_event 给 egui — 否则 egui 自己的
                        // 默认行为（Esc 关 popup、Enter 触发 focus 控件）会
                        // 和我们抢，导致按一下 Esc 既关 popup 又退全屏。
                        // 例外：在线字幕搜索面板打开 + 输入框聚焦时，把 Esc /
                        // Enter / Space 留给 egui（关闭 popup / 触发搜索 / 输入
                        // 空格），不抢。
                        let in_search_input = state.online_search_open;
                        if pressed && !in_search_input {
                            match code {
                                KeyCode::Escape => {
                                    if win.is_fullscreen() {
                                        win.toggle_fullscreen();
                                        state.fullscreen = win.is_fullscreen();
                                    } else {
                                        win.request_close();
                                    }
                                    continue;
                                }
                                KeyCode::Enter => {
                                    if !win.is_fullscreen() {
                                        win.toggle_fullscreen();
                                        state.fullscreen = win.is_fullscreen();
                                    }
                                    continue;
                                }
                                KeyCode::Space => {
                                    let cmd = [c"cycle".as_ptr(), c"pause".as_ptr(), std::ptr::null()];
                                    mp::mpv_command(player.handle(), cmd.as_ptr() as *mut _);
                                    continue;
                                }
                                _ => {}
                            }
                        }
                        // 把 Win32 VK 映射成 egui::Key。覆盖文字编辑/导航/常用
                        // 快捷键所需的最小集；其余按键我们没有 UI 用得上，丢
                        // 弃即可（keyup 也一并丢，egui 没记 down 不会卡住）。
                        let key = match code {
                            KeyCode::Escape => Some(egui::Key::Escape),
                            KeyCode::Space => Some(egui::Key::Space),
                            KeyCode::Enter => Some(egui::Key::Enter),
                            KeyCode::Other(vk) => translate_vk(vk),
                        };
                        // 修饰键单独维护一份状态。Shift / Ctrl / Alt 的 VK 同时
                        // 也走 Other(_) 派出去，但 egui 自己不靠它们读修饰键，
                        // 而是读每个 Event 上挂的 modifiers 字段，所以我们显式
                        // 追一遍 down/up 写到 current_modifiers。
                        if let Some(m) = vk_modifier(code) {
                            match m {
                                ModifierFlag::Shift => current_modifiers.shift = pressed,
                                ModifierFlag::Ctrl => {
                                    current_modifiers.ctrl = pressed;
                                    current_modifiers.command = pressed;
                                }
                                ModifierFlag::Alt => current_modifiers.alt = pressed,
                            }
                            hud.set_modifiers(current_modifiers);
                        }
                        if let Some(k) = key {
                            hud.push_event(egui::Event::Key {
                                key: k,
                                physical_key: Some(k),
                                pressed,
                                repeat: false,
                                modifiers: current_modifiers,
                            });
                        }
                    }
                    InputEvent::Char { ch } => {
                        // egui TextEdit 是靠 Event::Text 而不是 Event::Key 来
                        // 插入字符的。WM_CHAR 已经做完键盘布局 + IME 转换，
                        // 直接拼成 String 喂过去就好。Ctrl+A/C/V/X 等组合键
                        // 走 Event::Key，那条路径不会落在这里（控制字符在
                        // window.rs 的 WM_CHAR 处理里被过滤掉了）。
                        hud.push_event(egui::Event::Text(ch.to_string()));
                    }
                    InputEvent::Resize => {
                        // Will be picked up by client_size below; nothing
                        // to do here.
                        let _ = last_mouse_pos;
                    }
                }
            }

            let (cw, ch) = win.client_size();

            // 让 mpv 把视频画面避让底栏 / 右侧面板占用的区域。video-margin-ratio-*
            // 取 [0,1]，mpv 会把空出的区域填成黑色。**注意**：mpv 是按比例切视频
            // 渲染区且保持源宽高比，纵向砍掉 80px 等于整张视频整体缩小，源 16:9
            // 在 16:9 屏上瞬间出现两侧 letterbox 黑边（用户截图正是这个效果）。
            // 所以：
            //   - 非全屏：右侧 SidePanel 是真占位，整体收窄不会引起 letterbox；
            //     底栏出现时给 80px margin 避免字幕被压住，反正面板已经收过 → 无副作用
            //   - 全屏：margin 一律 0，HUD 直接覆盖在视频上（PotPlayer / VLC 同款），
            //     字幕短暂被压属于全屏 HUD 标准行为，3s 后自动消失
            let bottom_margin = if !state.fullscreen && hud.hud_visible() && ch > 0 {
                (80.0_f64 / ch as f64).clamp(0.0, 0.5)
            } else {
                0.0
            };
            // 非全屏：面板永远可见 + SidePanel 占位，视频跟 panel_w 同步收窄。
            // 全屏：右侧面板已经砍掉，永远 0。
            let right_margin = if !state.fullscreen && hud.panel_visible() && cw > 0 {
                let pw = crate::native_player::ui::side_panel_width(cw as f32) as f64;
                (pw / cw as f64).clamp(0.0, 0.5)
            } else {
                0.0
            };
            if (bottom_margin - last_margin_bottom).abs() > 1e-4 {
                let _ = player.set_property_str(
                    "video-margin-ratio-bottom",
                    &format!("{bottom_margin:.4}"),
                );
                last_margin_bottom = bottom_margin;
                player.request_redraw();
            }
            if (right_margin - last_margin_right).abs() > 1e-4 {
                let _ = player.set_property_str(
                    "video-margin-ratio-right",
                    &format!("{right_margin:.4}"),
                );
                last_margin_right = right_margin;
                player.request_redraw();
            }

            // 双击命中视频区域（即不在「当前可见的」右侧面板/底栏）→ 切全屏。
            //   - 右侧面板：仅在它当前可见时才把右侧那块算占用区。全屏 + 面板
            //     未弹起时，整片右侧仍是视频区，双击应能切全屏；旧逻辑不论
            //     可见性都按 panel_w 切掉，导致全屏中部双击没事但偏右双击
            //     不切回窗口
            //   - 底栏：80px ≈ 进度条 + 按钮一行；底栏隐藏时（hud_visible
            //     上一帧为 false）这块也是视频区
            if let Some((x, y)) = pending_double_click {
                let in_panel = if hud.panel_visible() {
                    let panel_w = crate::native_player::ui::side_panel_width(cw as f32);
                    x >= (cw as f32 - panel_w)
                } else {
                    false
                };
                let in_bottom = if hud.hud_visible() {
                    y >= (ch as f32 - 80.0)
                } else {
                    false
                };
                if !in_panel && !in_bottom {
                    win.toggle_fullscreen();
                    state.fullscreen = win.is_fullscreen();
                }
            }

            // mpv track-list 每秒拉一次（observe NODE 太重，字符串够用）；
            // 解析失败时 refresh_tracks_from_json 自己保留旧列表。
            if last_track_pull.elapsed() > Duration::from_millis(1000) {
                if let Some(json) = player.get_property_string("track-list") {
                    state.refresh_tracks_from_json(&json);
                }
                last_track_pull = Instant::now();
            }

            // 进入新资源后自动选字幕：优先级 已绑定 > 内嵌。
            //   - 等 track-list 拉到（state.tracks 非空，说明 mpv 已经把视频/音/字幕
            //     轨都吐出来了）+ current_sid 已经被推送过一次（说明 mpv 自己的
            //     --slang 也定下来了），再做我们的覆盖
            //   - 已绑定段：is_default=true 的优先，否则取第一条 → SetSubtitle(Some(url))
            //   - 内嵌段：取第一条 sub && !external → SetSubtitleTrack(id)。但如果
            //     mpv 已经选中了某条内嵌字幕（current_sid 是数字），就不覆盖
            //     ——尊重 mpv 自己根据 --slang/默认标记选的那条
            //   - 一旦决定就翻 auto_subtitle_done = true，避免重复触发。SwitchResource
            //     时重置回 false 让新资源能再来一次
            if !state.auto_subtitle_done && !state.tracks.is_empty() {
                let mpv_picked_internal = state
                    .current_sid
                    .as_deref()
                    .and_then(|s| s.parse::<i64>().ok())
                    .is_some();
                let bound_default = state
                    .current_resource()
                    .and_then(|r| {
                        r.subtitles
                            .iter()
                            .find(|s| s.is_default)
                            .or_else(|| r.subtitles.first())
                    })
                    .map(|s| s.url.clone());
                if let Some(url) = bound_default {
                    let curl = std::ffi::CString::new(url).unwrap_or_default();
                    let cmd = [
                        c"sub-add".as_ptr(),
                        curl.as_ptr(),
                        c"select".as_ptr(),
                        std::ptr::null(),
                    ];
                    mp::mpv_command(player.handle(), cmd.as_ptr() as *mut _);
                    state.auto_subtitle_done = true;
                } else if !mpv_picked_internal {
                    if let Some(t) = state
                        .tracks
                        .iter()
                        .find(|t| t.kind == "sub" && !t.external)
                    {
                        let s = t.id.to_string();
                        let cval = std::ffi::CString::new(s).unwrap_or_default();
                        mp::mpv_set_property_string(
                            player.handle(),
                            c"sid".as_ptr(),
                            cval.as_ptr(),
                        );
                    }
                    // 没字幕可选也算"做过决定"——不要每秒重试。
                    state.auto_subtitle_done = true;
                } else {
                    // mpv 自己已经选了内嵌字幕，没绑定字幕能盖。停手。
                    state.auto_subtitle_done = true;
                }
            }

            // 渲染策略：
            //   - 每次循环都让 mpv 把它"当前的内部帧"重画到 FBO 0。即使没有
            //     新帧（暂停 / 鼠标静止时 mpv 不产帧），mpv 也会幂等地重画上
            //     一帧的有效像素。这样 egui 永远在一个有效的视频底图上做
            //     alpha blend，避免 SwapBuffers 后 back buffer 内容未定义、
            //     egui 透明区域露出旧/脏像素的「抽搐」。早期版本只在 has_frame
            //     时才 render_frame，鼠标移出窗口时 16ms sleep 拉长 swap 间隔，
            //     双缓冲在某些驱动上把 back 还成 undefined → egui 半透明区
            //     就显得抖。
            //   - HUD 必须每次循环都绘制并 SwapBuffers，否则 egui 收不到
            //     鼠标点击 — 主循环卡在「等帧」时按钮就点不动了
            //     （M3.4 用户验收发现：暂停后再点播放无效）
            //   - 缓冲态（paused-for-cache）跳过 mpv render：mpv 此时会
            //     不规律重发当前帧+前后帧，导致 backbuffer 在两帧间来回
            //     跳，肉眼看就是"画面抽搐"。直接复用上一次的稳定帧即可。
            let new_video_frame = player.has_frame();
            if !state.buffering {
                // egui 上一帧留下的 GL 状态会污染 mpv 的下一次 render，
                // 必须在每次 mpv render 前显式恢复（详见 reset 函数注释）。
                reset_gl_for_mpv(hud.glow(), cw, ch);
                player.render_frame(cw, ch)?;
            }

            // egui paints over the same FBO 0 with alpha blending.
            let mut actions = hud.paint(&state, cw, ch);
            // 视频自然播完（END_FILE/reason=EOF）→ 自动跳下一集。
            // drain_mpv_events 在收到 EOF 时设置 pending_auto_next；这里
            // 消费一次后立即清零，避免最后一集 EOF 后 next 还是 None 时
            // 一直保留 true，下次任何刷新又触发。
            // SwitchResource action 走与用户手动点"下一集"完全一致的路径——
            // 设置 current_resource_id、清零 time_pos / duration / auto_subtitle_done、
            // 再 mpv loadfile 新 url。
            if state.pending_auto_next {
                state.pending_auto_next = false;
                let (_, next_target) =
                    crate::native_player::ui::derive_prev_next(&state);
                if let Some((id, url)) = next_target {
                    actions.push(
                        crate::native_player::controller::Action::SwitchResource { id, url },
                    );
                }
            }
            for action in actions {
                match &action {
                    crate::native_player::controller::Action::ToggleFullscreen => {
                        win.toggle_fullscreen();
                        state.fullscreen = win.is_fullscreen();
                    }
                    crate::native_player::controller::Action::SwitchResource { id, .. } => {
                        // 记下新当前源后再丢给 mpv loadfile（apply 里走）。
                        // 心跳快照里 position 立刻清零，避免下一 tick 把
                        // 旧位置带到新 resource_id 上。duration 等 mpv
                        // PROP_DURATION 触发后 state 自然刷新。
                        state.current_resource_id = Some(id.clone());
                        state.time_pos = 0.0;
                        state.duration = 0.0;
                        // 新资源重新走「自动选字幕」流程；老资源决定不带过去。
                        state.auto_subtitle_done = false;
                        action.apply(player.handle());
                    }
                    crate::native_player::controller::Action::SetSeason(s) => {
                        // 切换季 tab：只改状态，不动 mpv（用户接下来点集才换源）。
                        state.active_season = Some(*s);
                    }
                    crate::native_player::controller::Action::OpenSubtitleSearch => {
                        state.online_search_open = true;
                        // 关键词预填：用电影标题；如果空再 fallback 到当前源 filename。
                        if state.online_search_query.is_empty() {
                            let kw = state
                                .movie
                                .as_ref()
                                .map(|m| m.title.clone())
                                .filter(|s| !s.is_empty())
                                .or_else(|| {
                                    state.current_resource().map(|r| r.filename.clone())
                                })
                                .unwrap_or_default();
                            state.online_search_query = kw;
                        }
                        // 立即触发一次搜索，省得用户再点一下。
                        if !state.online_search_query.is_empty()
                            && !opts.api_base.is_empty()
                        {
                            if let Some(rid) = state.current_resource_id.clone() {
                                crate::native_player::online_subs::spawn_search(
                                    opts.api_base.clone(),
                                    rid,
                                    state.online_search_query.clone(),
                                    std::sync::Arc::clone(&state.online_search_state),
                                );
                            }
                        }
                    }
                    crate::native_player::controller::Action::CloseSubtitleSearch => {
                        state.online_search_open = false;
                    }
                    crate::native_player::controller::Action::RunSubtitleSearch(q) => {
                        state.online_search_query = q.clone();
                        if !q.is_empty() && !opts.api_base.is_empty() {
                            if let Some(rid) = state.current_resource_id.clone() {
                                crate::native_player::online_subs::spawn_search(
                                    opts.api_base.clone(),
                                    rid,
                                    q.clone(),
                                    std::sync::Arc::clone(&state.online_search_state),
                                );
                            }
                        }
                    }
                    crate::native_player::controller::Action::PreviewOnlineSubtitle {
                        candidate_id,
                        label,
                    } => {
                        if !opts.api_base.is_empty() {
                            if let Some(rid) = state.current_resource_id.clone() {
                                crate::native_player::online_subs::spawn_preview(
                                    opts.api_base.clone(),
                                    rid,
                                    candidate_id.clone(),
                                    label.clone(),
                                    std::sync::Arc::clone(&state.online_search_state),
                                    preview_tx.clone(),
                                );
                            }
                        }
                    }
                    crate::native_player::controller::Action::BindOnlineSubtitle {
                        candidate_id,
                        label,
                    } => {
                        if !opts.api_base.is_empty() {
                            if let Some(rid) = state.current_resource_id.clone() {
                                crate::native_player::online_subs::spawn_bind(
                                    opts.api_base.clone(),
                                    rid,
                                    candidate_id.clone(),
                                    label.clone(),
                                    std::sync::Arc::clone(&state.online_search_state),
                                    bind_tx.clone(),
                                );
                            }
                        }
                    }
                    crate::native_player::controller::Action::RequestDeleteSubtitle(sid) => {
                        // 先点「✕」 → 进入二次确认态。同一时间只允许一条字幕处于
                        // 待确认；点别的「✕」会替换掉前一个的态，避免菜单里多行
                        // 同时显示「确定 / 取消」看着乱。
                        state.pending_delete_sid = Some(sid.clone());
                    }
                    crate::native_player::controller::Action::CancelDeleteSubtitle => {
                        state.pending_delete_sid = None;
                    }
                    crate::native_player::controller::Action::ConfirmDeleteSubtitle(sid) => {
                        // 不立即从 state 摘字幕条目——等 worker 真的成功回执
                        // 才动 movie.resources，这样 worker 失败时 UI 还能看到
                        // 这条字幕（用户能从 last_message 知道为啥没删掉）。
                        if !opts.api_base.is_empty() {
                            if let Some(rid) = state.current_resource_id.clone() {
                                crate::native_player::online_subs::spawn_delete(
                                    opts.api_base.clone(),
                                    rid,
                                    sid.clone(),
                                    std::sync::Arc::clone(&state.online_search_state),
                                    delete_tx.clone(),
                                );
                            }
                        }
                        state.pending_delete_sid = None;
                    }
                    _ => action.apply(player.handle()),
                }
            }

            // 收 worker 完成事件 —— 跨线程，不能在 worker 里直接动 mpv，必须
            // 主循环消化。预览：mpv sub-add <tmp_path> select；同时把这条 PreviewSub
            // 记进 state，HUD 字幕菜单第三段「在线 · 临时预览」据此渲染。
            while let Ok(p) = preview_rx.try_recv() {
                let cmd_url = std::ffi::CString::new(p.path.as_str()).unwrap_or_default();
                let select = std::ffi::CString::new("select").unwrap();
                let cmd = [
                    c"sub-add".as_ptr(),
                    cmd_url.as_ptr(),
                    select.as_ptr(),
                    std::ptr::null(),
                ];
                mp::mpv_command(player.handle(), cmd.as_ptr() as *mut _);
                // 同 candidate_id 的旧 PreviewSub（用户对一条候选反复点预览）替换掉，
                // 避免菜单出现重复条目。label 用最新一次传入的。
                let label = state
                    .online_search_state
                    .lock()
                    .ok()
                    .and_then(|g| match &g.search {
                        crate::native_player::controller::SearchPhase::Loaded(items) => items
                            .iter()
                            .find(|c| c.candidate_id == p.candidate_id)
                            .map(|c| (c.label.clone(), c.format.clone())),
                        _ => None,
                    });
                let (label_str, format) = label.unwrap_or_else(|| (p.candidate_id.clone(), None));
                state
                    .preview_subtitles
                    .retain(|s| s.candidate_id != p.candidate_id);
                state
                    .preview_subtitles
                    .push(crate::native_player::controller::PreviewSub {
                        candidate_id: p.candidate_id,
                        label: label_str,
                        tmp_path: p.path,
                        format,
                    });
            }
            // 绑定完成：把新字幕条目注入 state.movie 当前 resource，跟初始
            // 外挂字幕走完全一样的渲染路径；同时 sub-add+select 让 mpv 立刻切上。
            // 如果之前有同候选的临时预览条目，把它从 preview_subtitles 剔除——
            // 已绑定的字幕走「已绑定」段渲染，不再保留临时预览。
            while let Ok(b) = bind_rx.try_recv() {
                if let (Some(rid), Some(movie)) =
                    (state.current_resource_id.clone(), state.movie.as_mut())
                {
                    if let Some(r) = movie.resources.iter_mut().find(|r| r.id == rid) {
                        r.subtitles.push(crate::native_player::meta::SubtitleMeta {
                            id: b.subtitle_id.clone(),
                            url: b.url.clone(),
                            label: b.label.clone(),
                            display_name: b.display_name.clone(),
                            format: b.format.clone(),
                            is_default: false,
                        });
                    }
                }
                // bind 走的是后端 URL，候选 id 我们手里有的最直接来源是 worker
                // 当时附带的 cid—— 但 BindReady 现在只回 subtitle 字段没回 cid。
                // 从 last_message / busy_candidate 反推也不稳；干脆按 url 匹配
                // 临时文件被替换的概率几乎为 0。退而求其次：bind 后清掉 *所有*
                // 同名 label 的预览条目（label 在 preview/bind 之间是稳定的）。
                if let Some(label) = b.label.as_ref() {
                    state.preview_subtitles.retain(|s| &s.label != label);
                }
                let cmd_url = std::ffi::CString::new(b.url.as_str()).unwrap_or_default();
                let select = std::ffi::CString::new("select").unwrap();
                let cmd = [
                    c"sub-add".as_ptr(),
                    cmd_url.as_ptr(),
                    select.as_ptr(),
                    std::ptr::null(),
                ];
                mp::mpv_command(player.handle(), cmd.as_ptr() as *mut _);
            }

            // 删除完成：worker 走 DELETE /resources/{rid}/subtitles/{sid}。成功的时候
            // 把这条字幕从 state.movie.resources[i].subtitles 摘掉，并通知 mpv
            // sub-remove 把外挂字幕轨道也下掉——避免菜单里没了，但 mpv 还在 select
            // 已删字幕的 url 卡住。失败的时候只清 pending 态、保留字幕条目让用户重试。
            while let Ok(d) = delete_rx.try_recv() {
                if d.ok {
                    let removed_url = if let (Some(rid), Some(movie)) =
                        (state.current_resource_id.clone(), state.movie.as_mut())
                    {
                        if let Some(r) =
                            movie.resources.iter_mut().find(|r| r.id == rid)
                        {
                            // 找到要删的条目并取出 url 之后再 retain，免得 retain 之
                            // 后还要再扫一遍。
                            let url = r
                                .subtitles
                                .iter()
                                .find(|s| s.id == d.subtitle_id)
                                .map(|s| s.url.clone());
                            r.subtitles.retain(|s| s.id != d.subtitle_id);
                            url
                        } else {
                            None
                        }
                    } else {
                        None
                    };
                    // mpv `sub-remove` 接 sid（数字），但我们手里没有数字——track-list
                    // 里能反查：external_filename == removed_url 的 sub track 即对应轨。
                    if let Some(url) = removed_url {
                        if let Some(track) = state
                            .tracks
                            .iter()
                            .find(|t| {
                                t.kind == "sub"
                                    && t.external
                                    && t.external_filename.as_deref()
                                        == Some(url.as_str())
                            })
                        {
                            let s = track.id.to_string();
                            let cval = std::ffi::CString::new(s).unwrap_or_default();
                            let cmd = [
                                c"sub-remove".as_ptr(),
                                cval.as_ptr(),
                                std::ptr::null(),
                            ];
                            mp::mpv_command(player.handle(), cmd.as_ptr() as *mut _);
                        }
                    }
                }
                // 不论成败，pending 态都已经在 ConfirmDeleteSubtitle 里清过了。
                let _ = d;
            }

            win.swap_buffers();
            player.report_swap();

            // 心跳快照：每 500ms 推一次到心跳线程的 mutex（线程内部
            // 自己再按 10s 节奏 POST）。频繁 update 是廉价的，目的是切集
            // 后下一个 tick 立刻拿到新 resource_id；别为了省锁去拉长间隔。
            if let Some(hb) = heartbeat.as_ref() {
                if last_heartbeat_push.elapsed() > Duration::from_millis(500) {
                    hb.update(ProgressSnapshot {
                        resource_id: state
                            .current_resource_id
                            .clone()
                            .unwrap_or_default(),
                        position_sec: state.time_pos,
                        duration_sec: state.duration,
                    });
                    last_heartbeat_push = Instant::now();
                }
            }

            // 没新视频帧时，让出 CPU；不要 busy-loop 1ms 挨着 swap
            // 也别睡太久，否则鼠标 hover 反馈/进度条拖动手感会卡。
            // ~16ms ≈ 60Hz UI tick；mpv 一旦产新帧 update_callback
            // 会立刻把 has_frame 翻 true，下一轮就刷视频。
            if !new_video_frame {
                std::thread::sleep(Duration::from_millis(16));
            }
        }

        // Tear down in reverse creation order. Hud first (frees GL
        // resources while the context is still current); then mpv
        // render context (inside MpvPlayer::drop); then the window
        // (releases the GL context last). 心跳线程在最后 join 即可——
        // 它不持 GL 资源，但要在主循环出来前推最后一次快照。
        if let Some(hb) = heartbeat.as_ref() {
            hb.update(ProgressSnapshot {
                resource_id: state
                    .current_resource_id
                    .clone()
                    .unwrap_or_default(),
                position_sec: state.time_pos,
                duration_sec: state.duration,
            });
        }
        hud.destroy();
        drop(player);
        drop(win);
        if let Some(hb) = heartbeat {
            hb.shutdown();
        }
    }

    Ok(())
}

/// Pull pending mpv events. Returns true on SHUTDOWN so the caller
/// breaks out of the frame loop.
unsafe fn drain_mpv_events(player: &MpvPlayer, state: &mut PlayerState) -> bool {
    unsafe {
        loop {
            let ev = mp::mpv_wait_event(player.handle(), 0.0);
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
            if id == mp::MPV_EVENT_PROPERTY_CHANGE {
                state.apply_property_change(ev);
            }
            // 注意：mpv 在 keep-open=yes 模式下不会发 END_FILE 事件——它停在
            // 最后一帧暂停，所以"自动下一集"不能依赖 END_FILE。我们改观察
            // `eof-reached` 属性（PROP_EOF_REACHED），由 apply_property_change
            // 直接在变 true 时设置 state.pending_auto_next。
        }
    }
}

/// Options the webview hands to the native player when the user picks
/// "play". The webview is responsible for resolving a movie/resource
/// into a concrete URL + auth headers + resume position; Rust just
/// plays whatever it is given. This keeps the Rust side dumb and lets
/// us reuse the existing TS API client / token logic without porting.
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayOptions {
    pub url: String,
    /// HTTP request headers mpv should send (Authorization, Cookie, ...)
    #[serde(default)]
    pub headers: Vec<(String, String)>,
    /// Resume position in seconds. 0 means "start from the beginning".
    #[serde(default)]
    pub start_time: f64,
    /// Movie metadata for the right-side details panel. Optional —
    /// without it the panel just hides. The webview already has the
    /// detail-page payload loaded so it costs nothing to forward; we
    /// don't want Rust to have to make its own backend calls.
    #[serde(default)]
    pub movie: Option<MovieMeta>,
    /// The currently playing resource id (matches an entry in
    /// `movie.resources`). Used to highlight the active episode/source
    /// in the right-side panel.
    #[serde(default)]
    pub current_resource_id: Option<String>,
    /// `cyber_device_id` from the webview's localStorage. The backend
    /// `/v1/user/history` endpoint identifies the user by this rather
    /// than by an Authorization header — see frontend user.ts:79-94.
    #[serde(default)]
    pub device_id: String,
    /// Backend root WITHOUT the trailing `/api`. Rust path-joins
    /// `/api/v1/...` itself.
    #[serde(default)]
    pub api_base: String,
    /// Optional pre-allocated session id from the webview (`pc-<uuid>`).
    /// If empty, the player generates one — but only if heartbeat actually
    /// runs (we need device_id + api_base before we'll spawn the thread).
    #[serde(default)]
    pub session_id: Option<String>,
}

/// Tauri command. Spawns the player on a dedicated thread so the async
/// runtime stays responsive. Returns once the native window has been
/// closed (Esc / "返回" button / video ended).
#[tauri::command]
pub async fn open_pc_player(options: PlayOptions) -> Result<(), String> {
    eprintln!(
        "[native_player] open_pc_player invoked: url={}, current_resource_id={:?}, device_id={}, api_base={}, headers_len={}, has_movie={}",
        options.url,
        options.current_resource_id,
        options.device_id,
        options.api_base,
        options.headers.len(),
        options.movie.is_some(),
    );
    let (tx, rx) = tokio::sync::oneshot::channel();
    std::thread::spawn(move || {
        let result = run_player_blocking(options);
        if let Err(ref e) = result {
            eprintln!("[native_player] run_player_blocking error: {e}");
        }
        let _ = tx.send(result);
    });
    rx.await.map_err(|e| format!("native player worker dropped: {e}"))?
}

/// Restore the OpenGL state mpv expects before each render() call.
///
/// egui_glow toggles BLEND/SCISSOR_TEST, binds VAOs/VBOs/programs, sets
/// scissor/viewport rectangles, and uploads textures with custom unpack
/// alignment. mpv's render path assumes a clean default state on entry
/// and ADVANCED_CONTROL=0 only restores a subset on exit, so on the
/// SECOND iteration we feed mpv whatever egui happened to leave behind.
///
/// This reset matches what mpv.net/ImPlay do between their UI and mpv
/// passes. See render_gl.h §49-67 for the canonical "non-default state"
/// list.
fn reset_gl_for_mpv(gl: &glow::Context, w: i32, h: i32) {
    unsafe {
        gl.bind_framebuffer(glow::FRAMEBUFFER, None);
        gl.bind_vertex_array(None);
        gl.bind_buffer(glow::ARRAY_BUFFER, None);
        gl.bind_buffer(glow::ELEMENT_ARRAY_BUFFER, None);
        gl.bind_buffer(glow::PIXEL_UNPACK_BUFFER, None);
        gl.use_program(None);
        gl.disable(glow::SCISSOR_TEST);
        gl.disable(glow::BLEND);
        gl.disable(glow::CULL_FACE);
        gl.disable(glow::DEPTH_TEST);
        gl.disable(glow::STENCIL_TEST);
        gl.pixel_store_i32(glow::UNPACK_ALIGNMENT, 4);
        gl.pixel_store_i32(glow::UNPACK_ROW_LENGTH, 0);
        gl.viewport(0, 0, w.max(1), h.max(1));
        gl.color_mask(true, true, true, true);
        gl.depth_mask(true);
    }
}

/// 修饰键标记。Win32 把 Shift / Ctrl / Alt 通过 VK_SHIFT(0x10) / VK_CONTROL
/// (0x11) / VK_MENU(0x12) 经 WM_KEYDOWN 送上来；用左右版本（VK_L/RSHIFT 等）
/// 时也认。我们不区分左右，反正 egui::Modifiers 也不区分。
#[derive(Debug, Clone, Copy)]
enum ModifierFlag {
    Shift,
    Ctrl,
    Alt,
}

fn vk_modifier(code: KeyCode) -> Option<ModifierFlag> {
    let vk = match code {
        KeyCode::Other(v) => v,
        _ => return None,
    };
    match vk {
        0x10 | 0xA0 | 0xA1 => Some(ModifierFlag::Shift),
        0x11 | 0xA2 | 0xA3 => Some(ModifierFlag::Ctrl),
        0x12 | 0xA4 | 0xA5 => Some(ModifierFlag::Alt),
        _ => None,
    }
}

/// Win32 VK → egui::Key。覆盖文字编辑、导航、Ctrl+A/C/V/X、字母数字所需。
/// 不在表里的 VK 一律返回 None（HUD 用不到）。VK 数值参考 winuser.h。
fn translate_vk(vk: u32) -> Option<egui::Key> {
    use egui::Key;
    Some(match vk {
        0x08 => Key::Backspace,
        0x09 => Key::Tab,
        0x0D => Key::Enter,
        0x1B => Key::Escape,
        0x20 => Key::Space,
        0x21 => Key::PageUp,
        0x22 => Key::PageDown,
        0x23 => Key::End,
        0x24 => Key::Home,
        0x25 => Key::ArrowLeft,
        0x26 => Key::ArrowUp,
        0x27 => Key::ArrowRight,
        0x28 => Key::ArrowDown,
        0x2D => Key::Insert,
        0x2E => Key::Delete,
        // 0x30..=0x39 是数字 0-9（顶行），0x41..=0x5A 是字母 A-Z。
        0x30 => Key::Num0,
        0x31 => Key::Num1,
        0x32 => Key::Num2,
        0x33 => Key::Num3,
        0x34 => Key::Num4,
        0x35 => Key::Num5,
        0x36 => Key::Num6,
        0x37 => Key::Num7,
        0x38 => Key::Num8,
        0x39 => Key::Num9,
        0x41 => Key::A,
        0x42 => Key::B,
        0x43 => Key::C,
        0x44 => Key::D,
        0x45 => Key::E,
        0x46 => Key::F,
        0x47 => Key::G,
        0x48 => Key::H,
        0x49 => Key::I,
        0x4A => Key::J,
        0x4B => Key::K,
        0x4C => Key::L,
        0x4D => Key::M,
        0x4E => Key::N,
        0x4F => Key::O,
        0x50 => Key::P,
        0x51 => Key::Q,
        0x52 => Key::R,
        0x53 => Key::S,
        0x54 => Key::T,
        0x55 => Key::U,
        0x56 => Key::V,
        0x57 => Key::W,
        0x58 => Key::X,
        0x59 => Key::Y,
        0x5A => Key::Z,
        _ => return None,
    })
}
