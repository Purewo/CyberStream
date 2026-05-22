// CyberStream PC native player · egui HUD.
//
// Drawn ON TOP of the libmpv frame in the same default framebuffer.
// Order per frame (driven by mod.rs):
//   1. mpv_render_context_render → fills FBO 0 with the video frame
//   2. egui paint pass → blends transport bar + top bar over the same
//      FBO 0 (alpha-blended; non-control areas have alpha=0 so video
//      shows through)
//   3. SwapBuffers
//
// Implementation notes:
//   - egui_glow's `Painter` needs a `glow::Context`, which we build once
//     from PlayerWindow::get_proc_address.
//   - egui takes `RawInput` (mouse/keyboard/time) per frame and gives
//     back a list of `ClippedPrimitive` to draw plus a `PlatformOutput`
//     (cursor shape etc) we can ignore for M3.2.
//   - Visual tone matches the React PcPlayer: black overlay strips with
//     #22d3ee (cyan) accents. Auto-hide after 3s of mouse stillness is
//     M3.3 — for M3.2 the HUD is always visible to make sure controls
//     work first.

use std::sync::Arc;

use egui::{Color32, FontData, FontDefinitions, FontFamily, Pos2, Rect, Stroke, Vec2};
use egui_glow::Painter;

use crate::native_player::controller::{Action, OnlineCandidate, PlayerState, SearchPhase};
use crate::native_player::window::PlayerWindow;

/// Segoe Fluent Icons (Win11) / Segoe MDL2 Assets (Win10) 的 Unicode 私有
/// 区码点。这两个字体把媒体控件图标作为单个字符放在 PUA (E000–F8FF) 里，
/// 把对应字符喂给 painter.text 就能渲染出 Material 风格的图标。
///
/// 字体加载在 load_cjk_fonts 里把 SegoeIcons.ttf / segmdl2.ttf 加进
/// proportional family 的 fallback 链，所以下面这些 char 在没装这两个
/// 字体的系统上会回退到 □（很罕见——Win10/Win11 默认就有）。
mod icons {
    pub const PREVIOUS: &str = "\u{E892}";   // Previous (上一集)
    pub const NEXT: &str = "\u{E893}";       // Next (下一集)
    pub const PLAY: &str = "\u{E768}";       // Play
    pub const PAUSE: &str = "\u{E769}";      // Pause
    pub const VOLUME: &str = "\u{E767}";     // Volume
    pub const MUTE: &str = "\u{E74F}";       // Mute
    pub const FULLSCREEN: &str = "\u{E740}"; // FullScreen
    pub const BACK_TO_WINDOW: &str = "\u{E73F}"; // BackToWindow
    pub const SUBTITLE: &str = "\u{ED1E}";   // ClosedCaption
    pub const AUDIO: &str = "\u{E8D6}";      // Audio
    pub const SPEED: &str = "\u{EC4A}";      // Speed (FastForward 兜底备选)
    pub const CHEVRON_DOWN: &str = "\u{E70D}"; // ChevronDown
    pub const DELETE: &str = "\u{E74D}";     // Delete (垃圾桶)
}

pub struct Hud {
    ctx: egui::Context,
    glow: Arc<glow::Context>,
    painter: Painter,
    raw_input: egui::RawInput,
    /// epoch for `predicted_dt`/animation timing
    start: std::time::Instant,
    /// Last instant the mouse moved or clicked. Drives "鼠标静止 3s 隐藏
    /// HUD 全部控件" — PotPlayer-style auto-hide. Initialised to now()
    /// so the HUD is visible at startup.
    last_mouse_activity: std::time::Instant,
    /// Cached visibility of bottom bar / right panel from the last paint.
    /// 主循环用这个去推导 mpv 的 video-margin-ratio-* —— 让视频画面
    /// 自己腾出底栏/右栏区域，避免硬叠在视频上盖住字幕。
    last_hud_visible: bool,
    last_panel_visible: bool,
    /// 在线字幕搜索面板的"输入框 buffer"。state.online_search_query 是
    /// 主循环消化 RunSubtitleSearch 后写入的"已提交关键词"；输入框还在
    /// 编辑状态时的实时文本必须 UI 自己 cache 一份。第一次打开搜索面板
    /// 时同步 state.online_search_query 进来；用户按回车/搜索按钮再
    /// 通过 Action 推回去。
    search_query_buf: String,
    /// 上一帧 online_search_open 的值——用于检测「刚刚打开」事件，
    /// 同步 buf 一次。
    search_open_prev: bool,
    /// 上次实际作为「mouse activity」处理的鼠标坐标。Win32 WM_MOUSEMOVE
    /// 在窗口 hover 期间会以同一坐标反复触发（焦点切换、亚像素抖动、
    /// 鼠标 capture 进出等），导致 last_mouse_activity 不停被刷新——
    /// 全屏后 HUD 即便用户没动鼠标也每隔几秒就弹出来。这里 cache 上次
    /// 坐标，下一次 PointerMoved 必须比上次坐标偏移超过阈值才算 activity。
    last_activity_pos: Option<(f32, f32)>,
}

impl Hud {
    /// Build a glow Context from the wgl one currently current on this
    /// thread, then construct an egui_glow Painter on top of it. Must
    /// be called AFTER `PlayerWindow::create`.
    pub fn new() -> Result<Self, String> {
        let glow_ctx = unsafe {
            glow::Context::from_loader_function(|s| {
                PlayerWindow::get_proc_address(s)
            })
        };
        let glow_arc = Arc::new(glow_ctx);
        let painter = Painter::new(glow_arc.clone(), "", None, false)
            .map_err(|e| format!("egui_glow Painter: {e}"))?;

        let ctx = egui::Context::default();
        // Load custom theme — black overlay + cyan accents to match the
        // React PcPlayer look.
        ctx.set_visuals(make_theme());
        // egui's default font set has no CJK glyphs, so Chinese labels
        // render as boxes. Pull a system CJK font and stick it at the
        // front of both font families.
        if let Some(fonts) = load_cjk_fonts() {
            ctx.set_fonts(fonts);
        }

        Ok(Self {
            ctx,
            glow: glow_arc,
            painter,
            raw_input: egui::RawInput::default(),
            start: std::time::Instant::now(),
            last_mouse_activity: std::time::Instant::now(),
            last_hud_visible: true,
            last_panel_visible: true,
            search_query_buf: String::new(),
            search_open_prev: false,
            last_activity_pos: None,
        })
    }

    /// Update the input state for the next frame. mod.rs's window
    /// message loop fills these via `push_event`.
    pub fn update_screen_size(&mut self, w: i32, h: i32) {
        let size = Vec2::new(w as f32, h as f32);
        self.raw_input.screen_rect = Some(Rect::from_min_size(Pos2::ZERO, size));
    }

    pub fn push_event(&mut self, ev: egui::Event) {
        self.raw_input.events.push(ev);
    }

    pub fn set_modifiers(&mut self, m: egui::Modifiers) {
        self.raw_input.modifiers = m;
    }

    /// Build & paint the HUD for one frame. Returns the queued actions
    /// the caller should apply to libmpv (toggle pause, seek, volume).
    pub fn paint(&mut self, state: &PlayerState, screen_w: i32, screen_h: i32) -> Vec<Action> {
        // Fill out the rest of the RawInput.
        self.raw_input.time = Some(self.start.elapsed().as_secs_f64());
        self.update_screen_size(screen_w, screen_h);

        // 决定右侧面板是否显示：
        //   - 非全屏：永远显示，跟底栏一起常驻
        // 决定面板/底栏的显示：
        //   - 非全屏：两者常驻
        //   - 全屏：右侧面板永久隐藏；底栏 3s 鼠标活动后显示
        //   全屏下用户跳集走底栏的上一集 / 下一集，跨集跳转可退全屏。
        //   把面板砍掉以后，互斥逻辑、悬停粘性、Area 浮层全部消失，鼠标
        //   到右边沿不会再触发任何东西，体验跟 PotPlayer 沉浸态一致。
        let mut latest_mouse_pos: Option<(f32, f32)> = None;
        let mut had_mouse_activity = false;
        // 阈值：移动超过 2 像素才算"用户真的动了鼠标"。Win32 WM_MOUSEMOVE
        // 会以同一坐标重复触发（焦点切换、其他窗口重绘、capture 进出、
        // 亚像素抖动），不过滤的话全屏 HUD 会被这些事件不断"唤醒"，看
        // 起来像每隔几秒自己弹一下。2px 抗了亚像素抖动，又不会真把人为
        // 滑动的小幅度滤掉。
        const MOVE_EPS: f32 = 2.0;
        for ev in &self.raw_input.events {
            match ev {
                egui::Event::PointerMoved(p) => {
                    latest_mouse_pos = Some((p.x, p.y));
                    let moved = match self.last_activity_pos {
                        None => true,
                        Some((lx, ly)) => {
                            (p.x - lx).abs() > MOVE_EPS || (p.y - ly).abs() > MOVE_EPS
                        }
                    };
                    if moved {
                        had_mouse_activity = true;
                        self.last_activity_pos = Some((p.x, p.y));
                    }
                }
                egui::Event::PointerButton { .. } | egui::Event::MouseWheel { .. } => {
                    had_mouse_activity = true;
                }
                _ => {}
            }
        }
        if had_mouse_activity {
            self.last_mouse_activity = std::time::Instant::now();
        }
        let _ = latest_mouse_pos;

        let hud_active_recent =
            self.last_mouse_activity.elapsed() < std::time::Duration::from_millis(3000);

        let (hud_visible, panel_visible) = if state.fullscreen {
            (hud_active_recent, false)
        } else {
            (true, true)
        };
        self.last_hud_visible = hud_visible;
        self.last_panel_visible = panel_visible;

        let raw_input = std::mem::take(&mut self.raw_input);

        // 把搜索 buf "借出来"——闭包要借 self.ctx 做 mut，但同时也想动 buf；
        // mem::take 拿走后 run 完成再写回，绕开二次借用。
        // search_open_prev 同理：进闭包前快照，闭包内做 newly_opened 判断后
        // 写回。
        let mut buf = std::mem::take(&mut self.search_query_buf);
        let prev_open = self.search_open_prev;

        let mut actions = Vec::new();
        let output = self.ctx.run(raw_input, |ctx| {
            draw_ui(
                ctx,
                state,
                panel_visible,
                hud_visible,
                &mut actions,
                &mut buf,
                prev_open,
            );
        });

        // 写回 buf + 同步 search_open_prev。
        self.search_query_buf = buf;
        self.search_open_prev = state.online_search_open;

        let pixels_per_point = self.ctx.pixels_per_point();
        let primitives = self.ctx.tessellate(output.shapes, pixels_per_point);

        self.painter.paint_and_update_textures(
            [screen_w as u32, screen_h as u32],
            pixels_per_point,
            &primitives,
            &output.textures_delta,
        );

        actions
    }

    /// Hand egui_glow's underlying GL context out so the frame loop can
    /// reset state between egui's paint and mpv's next render.
    pub fn glow(&self) -> &Arc<glow::Context> {
        &self.glow
    }

    /// Bottom bar visibility from the most recent paint. Frame loop
    /// reads this to tell mpv how much bottom margin to reserve so
    /// burned-in subtitles aren't covered by the control strip.
    pub fn hud_visible(&self) -> bool {
        self.last_hud_visible
    }

    /// Right-side panel visibility from the most recent paint. Same
    /// purpose as `hud_visible` but for the horizontal axis.
    pub fn panel_visible(&self) -> bool {
        self.last_panel_visible
    }

    /// Free GL resources before the GL context goes away.
    pub fn destroy(mut self) {
        self.painter.destroy();
        // glow::Context drops on its own; we hold no extra GL state.
        drop(self.glow);
    }
}

// ---- HUD layout ----------------------------------------------------------

/// 右侧详情面板宽度：1280→280, 1920→350 线性插值，用 paint() 提前
/// 算出来好确认 reveal 区域的左沿。pub 是为了 mod.rs 在判断双击命中
/// 区域时能复用同一份逻辑。
pub fn side_panel_width(screen_w: f32) -> f32 {
    if screen_w <= 1280.0 {
        280.0
    } else if screen_w >= 1920.0 {
        350.0
    } else {
        280.0 + (screen_w - 1280.0) * (350.0 - 280.0) / (1920.0 - 1280.0)
    }
}

fn draw_ui(
    ctx: &egui::Context,
    state: &PlayerState,
    panel_visible: bool,
    hud_visible: bool,
    actions: &mut Vec<Action>,
    search_buf: &mut String,
    search_open_prev: bool,
) {
    let cyan = Color32::from_rgb(0x22, 0xd3, 0xee);
    // 注意：egui 的 Color32 是「预乘 alpha」存储，但我们以「带透明度的常规 RGBA」
    // 思维写颜色——所以一律用 from_rgba_unmultiplied 让 egui 自己去乘。如果用
    // from_rgba_premultiplied 写 (255,255,255,12) 这种 R/G/B 远大于 alpha 的值，
    // egui 会按非法预乘色去 blend，结果是「整面板亮成纯白」。
    let panel_bg = Color32::from_rgba_unmultiplied(10, 12, 16, 245);

    // 右侧详情面板：窗口模式常驻；全屏时仅在鼠标靠右才显示。
    let screen_w = ctx.screen_rect().width();
    let panel_w = side_panel_width(screen_w);

    // 右侧详情面板：仅在非全屏时显示。
    //   全屏沉浸态把右侧面板砍掉了 ——
    //     · 跨集跳转走底栏的上一集 / 下一集，跳跃多集请退全屏
    //     · 互斥/悬停粘性/Area vs SidePanel 双模式全部消失，鼠标到右边不再
    //       触发任何东西，体验跟 PotPlayer 沉浸态一致
    //   video-margin-ratio-right 在 mod.rs 里只跟非全屏的 panel_w 同步；
    //   全屏永远 0，视频铺满。
    if !state.fullscreen {
        let _ = panel_visible; // panel_visible 永远 true，仅占位别 unused
        egui::SidePanel::right("details_panel")
            .resizable(false)
            .exact_width(panel_w)
            .frame(egui::Frame {
                fill: panel_bg,
                inner_margin: egui::Margin::same(0),
                stroke: egui::Stroke::new(
                    1.0,
                    Color32::from_rgba_unmultiplied(255, 255, 255, 18),
                ),
                ..Default::default()
            })
            .show_separator_line(false)
            .show(ctx, |ui| {
                draw_details_panel(ui, state, actions, cyan);
            });
    }

    // 底栏：进度条 + 时间 + 播放/全屏 + 缓冲提示。鼠标静止 3s 后整体隐藏。
    if hud_visible {
        // 把底栏「背板」做成上下渐变（顶部透明 → 底部 0.85 黑），让进度条
        // 上沿无缝融入视频，去掉那种"控件块硬贴在画面上"的违和感。
        // egui::Frame.fill 只能纯色，要渐变得自己 Painter 涂——这里用上方
        // 80px 高的 transparent→bg 渐变带 + 底部纯色面板拼出来。
        let bar_h: f32 = 96.0; // 整个底栏目视高度（含 fade）
        let panel_top = ctx.screen_rect().bottom() - bar_h;
        let fade_top = panel_top - 36.0; // 再往上拉 36px 做柔光过渡
        let painter_bg = ctx.layer_painter(egui::LayerId::new(
            egui::Order::Background,
            egui::Id::new("bottom_fade"),
        ));
        // 顶部柔光过渡：从全透明到 0.55 黑（不要一上来就 0.9，看着特别闷）。
        // SidePanel 已经把 central area 收窄了，但这层 fade 用 LayerId::Background
        // 直接画屏幕坐标——所以面板可见时手动把 fade 切到面板左沿，不让
        // 半透明黑色横穿到面板下方。
        let fade_right = if panel_visible {
            ctx.screen_rect().right() - panel_w
        } else {
            ctx.screen_rect().right()
        };
        for i in 0..18 {
            let t = i as f32 / 17.0;
            let y0 = fade_top + (panel_top - fade_top) * t;
            let y1 = fade_top + (panel_top - fade_top) * ((i as f32 + 1.0) / 17.0);
            let a = (t * 140.0).round() as u8;
            painter_bg.rect_filled(
                egui::Rect::from_min_max(
                    egui::pos2(0.0, y0),
                    egui::pos2(fade_right, y1),
                ),
                egui::CornerRadius::ZERO,
                Color32::from_rgba_unmultiplied(0, 0, 0, a),
            );
        }

        egui::TopBottomPanel::bottom("bottom_bar")
        .frame(egui::Frame {
            fill: Color32::from_rgba_unmultiplied(4, 8, 14, 235),
            inner_margin: egui::Margin {
                left: 28,
                right: 28,
                top: 10,
                bottom: 14,
            },
            stroke: egui::Stroke::NONE,
            ..Default::default()
        })
        .show_separator_line(false)
        .show(ctx, |ui| {
            // ── 第 1 行：横跨整宽的赛博进度条 ──────────────────────────────
            // 用 Painter 自己画：底部低亮度青色凹槽 + 顶部高亮 trail + 菱形把手 +
            // 顶部辉光晕，符合赛博风。Slider widget 自带的小灰球太朴素。
            draw_progress_bar(ui, state, actions, cyan);

            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new(format_time(state.time_pos))
                        .color(Color32::WHITE)
                        .monospace()
                        .size(12.0),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(
                        egui::RichText::new(format_time(state.duration))
                            .color(Color32::from_gray(170))
                            .monospace()
                            .size(12.0),
                    );
                    if state.buffering {
                        ui.add_space(8.0);
                        ui.label(
                            egui::RichText::new("● 缓冲中")
                                .color(cyan)
                                .size(11.5),
                        );
                    }
                });
            });

            ui.add_space(8.0);

            // ── 第 2 行：左边播控 / 中间弹性 / 右边菜单 ─────────────────────
            ui.horizontal(|ui| {
                let (prev_target, next_target) = derive_prev_next(state);

                // 上一集 — 圆形 ghost
                draw_ghost_circle(ui, icons::PREVIOUS, "上一集", prev_target.is_some(), cyan, || {
                    if let Some((id, url)) = prev_target.clone() {
                        actions.push(Action::SwitchResource { id, url });
                    }
                });
                ui.add_space(6.0);

                // 主控播放/暂停 — 实心青色大圆，赛博焦点
                draw_primary_circle(
                    ui,
                    if state.paused { icons::PLAY } else { icons::PAUSE },
                    cyan,
                    || actions.push(Action::TogglePause),
                );
                ui.add_space(6.0);

                // 下一集
                draw_ghost_circle(ui, icons::NEXT, "下一集", next_target.is_some(), cyan, || {
                    if let Some((id, url)) = next_target.clone() {
                        actions.push(Action::SwitchResource { id, url });
                    }
                });
                ui.add_space(14.0);

                // 音量：图标按钮（mute 切换）+ 紧凑小滑条
                let vol_glyph = if state.muted || state.volume <= 0.5 {
                    icons::MUTE
                } else {
                    icons::VOLUME
                };
                draw_ghost_circle(ui, vol_glyph, "静音切换", true, cyan, || {
                    actions.push(Action::ToggleMute);
                });
                ui.add_space(4.0);
                let mut vol = state.volume.clamp(0.0, 100.0);
                // egui::Slider 默认把"知"画成白色描边圆，跟整套青色赛博风
                // 不搭。这里用 scope 局部覆盖 widgets.inactive/hovered/active
                // 的 bg_fill + fg_stroke + bg_stroke，让 knob 变成实心青球；
                // scope 退出 style 自动还原，不影响后面控件。
                // egui 用 active visuals 画"正在被 drag"的 knob、用 hovered
                // 画 hover 态、其他时候用 inactive；三态都得改否则会闪白。
                let vol_resp = ui.scope(|ui| {
                    let v = &mut ui.style_mut().visuals.widgets;
                    let cyan_solid = cyan;
                    let cyan_dim = Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 200);
                    let no_stroke = egui::Stroke::NONE;
                    for state_ref in [&mut v.inactive, &mut v.hovered, &mut v.active] {
                        state_ref.bg_fill = cyan_solid;
                        state_ref.weak_bg_fill = cyan_solid;
                        // bg_stroke 是 Slider knob 的描边；置 NONE 让圆变实心。
                        state_ref.bg_stroke = no_stroke;
                        // fg_stroke 决定 trailing_fill 那段填充条的颜色 + Slider
                        // 轨道线条；统一青色保证 trail 跟 knob 同色融为一体。
                        state_ref.fg_stroke = egui::Stroke::new(2.0, cyan_dim);
                    }
                    ui.add_sized(
                        egui::vec2(110.0, 16.0),
                        egui::Slider::new(&mut vol, 0.0..=100.0)
                            .show_value(false)
                            .trailing_fill(true),
                    )
                }).inner;
                if vol_resp.changed() {
                    actions.push(Action::SetVolume(vol));
                }

                // 右对齐：字幕 / 音轨 / 倍速 / 全屏
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let fs_glyph = if state.fullscreen {
                        icons::BACK_TO_WINDOW
                    } else {
                        icons::FULLSCREEN
                    };
                    draw_chip_button(
                        ui,
                        fs_glyph,
                        cyan,
                        state.fullscreen,
                        || actions.push(Action::ToggleFullscreen),
                    );
                    ui.add_space(6.0);
                    draw_speed_menu(ui, state, actions, cyan);
                    ui.add_space(6.0);
                    draw_audio_menu(ui, state, actions, cyan);
                    ui.add_space(6.0);
                    draw_subtitle_menu(ui, state, actions, cyan);
                });
            });
        });
    }

    // 在线字幕搜索面板：覆盖在所有 HUD 之上，独立于 hud_visible（即使
    // 鼠标静止也保持显示——用户正在操作，不能突然消失）。
    if state.online_search_open {
        // 第一次打开：用 state 里主循环已经填好的关键词初始化 buf。
        if !search_open_prev {
            search_buf.clear();
            search_buf.push_str(&state.online_search_query);
        }
        draw_subtitle_search_window(ctx, state, actions, cyan, search_buf);
    }

    let _ = Stroke::NONE;
}

/// 派生上下集目标。规则：
///   - 取 state.movie.seasons 中匹配 active_season（或 current_resource 所在
///     season，再或 seasons[0]）的那一组 resource_ids
///   - 在该组里找 current_resource_id 的位置
///   - 前面一项 → 上一集；后面一项 → 下一集
///   - 找不到（电影、单文件、首集/末集）→ None
/// 返回值统一是 Option<(id, url)>，方便 HUD 直接派发 SwitchResource。
fn derive_prev_next(state: &PlayerState) -> (Option<(String, String)>, Option<(String, String)>) {
    let movie = match &state.movie {
        Some(m) => m,
        None => return (None, None),
    };
    let cur_id = match state.current_resource_id.as_deref() {
        Some(s) => s,
        None => return (None, None),
    };
    // 优先用 state.active_season；再 fall back 到当前 resource 自带的 season；
    // 最后兜到 seasons[0]。
    let active = state
        .active_season
        .or_else(|| state.current_resource().and_then(|r| r.season))
        .or_else(|| movie.seasons.first().map(|s| s.season));
    // 如果连 seasons 都没有（电影），就把 movie.resources 当成单组。
    let ids: Vec<&str> = if let Some(season) = active {
        movie
            .seasons
            .iter()
            .find(|s| s.season == season)
            .map(|s| s.resource_ids.iter().map(|s| s.as_str()).collect())
            .unwrap_or_default()
    } else {
        movie.resources.iter().map(|r| r.id.as_str()).collect()
    };
    if ids.is_empty() {
        return (None, None);
    }
    let pos = match ids.iter().position(|x| *x == cur_id) {
        Some(p) => p,
        None => return (None, None),
    };
    let lookup = |idx: usize| -> Option<(String, String)> {
        let id = ids.get(idx)?;
        let r = movie.resources.iter().find(|r| r.id == *id)?;
        if r.url.is_empty() {
            None
        } else {
            Some((r.id.clone(), r.url.clone()))
        }
    };
    let prev = if pos > 0 { lookup(pos - 1) } else { None };
    let next = lookup(pos + 1);
    (prev, next)
}

/// 圆形 / 类圆形图标按钮 —— 透明底 + hover 时浅青描边，参考 web Player
/// 的 ghost icon button。给上下集、静音、占位符号用。
fn draw_icon_button(
    ui: &mut egui::Ui,
    label: &str,
    tooltip: &str,
    enabled: bool,
    on_click: impl FnOnce(),
) {
    let cyan = Color32::from_rgb(0x22, 0xd3, 0xee);
    let text_color = if enabled {
        Color32::from_gray(235)
    } else {
        Color32::from_gray(95)
    };
    // 先 reserve 一个固定尺寸的 rect，用 painter 自己画——比 Frame+Label
    // 更可控（不带 inner padding 的微妙差异），看着也更整齐。
    let size = egui::vec2(34.0, 30.0);
    let (rect, resp) = ui.allocate_exact_size(
        size,
        if enabled {
            egui::Sense::click()
        } else {
            egui::Sense::hover()
        },
    );
    let resp = resp.on_hover_text(tooltip);
    let hovered = enabled && resp.hovered();
    let painter = ui.painter();
    if hovered {
        painter.rect_filled(
            rect,
            egui::CornerRadius::same(8),
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 30),
        );
        painter.rect_stroke(
            rect,
            egui::CornerRadius::same(8),
            egui::Stroke::new(1.0, cyan.gamma_multiply(0.7)),
            egui::StrokeKind::Inside,
        );
    }
    painter.text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        label,
        egui::FontId::proportional(14.0),
        if hovered { cyan } else { text_color },
    );
    if enabled && resp.clicked() {
        on_click();
    }
}

/// 横跨整宽的进度条，赛博风：双层凹槽 + 高亮 trail + 菱形把手 + 顶部辉光晕。
/// 自己用 Painter 画，不走 egui::Slider — Slider 默认外观太朴素而且滑块太小。
fn draw_progress_bar(
    ui: &mut egui::Ui,
    state: &PlayerState,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    let max = state.duration.max(1.0);
    let cur = state.time_pos.clamp(0.0, max);
    let progress = (cur / max).clamp(0.0, 1.0) as f32;

    // 进度条占整行可用宽度，hit 区高 18px（含上下 padding 让鼠标好抓）。
    let avail_w = ui.available_width();
    let (rect, resp) = ui.allocate_exact_size(
        egui::vec2(avail_w, 18.0),
        egui::Sense::click_and_drag(),
    );
    let painter = ui.painter();

    // 真正的轨道居中 4px 高；hover 时长到 6px，赛博「抬升」感。
    let hover = resp.hovered() || resp.is_pointer_button_down_on();
    let track_h: f32 = if hover { 6.0 } else { 4.0 };
    let center_y = rect.center().y;
    let track_rect = egui::Rect::from_min_max(
        egui::pos2(rect.left(), center_y - track_h / 2.0),
        egui::pos2(rect.right(), center_y + track_h / 2.0),
    );

    // 背板：暗青色凹槽 + 微弱底光让它看着不是死黑。
    painter.rect_filled(
        track_rect,
        egui::CornerRadius::same((track_h / 2.0) as u8),
        Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 36),
    );

    // 已播放区段：青色实心 + 顶部一道更亮的高光线。
    let fill_right = rect.left() + avail_w * progress;
    let fill_rect = egui::Rect::from_min_max(
        egui::pos2(rect.left(), track_rect.top()),
        egui::pos2(fill_right, track_rect.bottom()),
    );
    painter.rect_filled(
        fill_rect,
        egui::CornerRadius::same((track_h / 2.0) as u8),
        cyan,
    );
    // 顶部 1px 高光 — 让 trail 像有体积。
    if fill_rect.width() > 2.0 {
        painter.rect_filled(
            egui::Rect::from_min_max(
                egui::pos2(fill_rect.left(), fill_rect.top()),
                egui::pos2(fill_rect.right(), fill_rect.top() + 1.0),
            ),
            egui::CornerRadius::ZERO,
            Color32::from_rgba_unmultiplied(255, 255, 255, 110),
        );
    }

    // 把手：菱形（赛博更搭，圆球太常规）。hover 时尺寸放大 + 加辉光圈。
    let knob_x = fill_right;
    let knob_size = if hover { 14.0_f32 } else { 11.0_f32 };
    // 菱形 = 4 个点的 convex_polygon
    let knob_pts = vec![
        egui::pos2(knob_x, center_y - knob_size / 2.0),
        egui::pos2(knob_x + knob_size / 2.0, center_y),
        egui::pos2(knob_x, center_y + knob_size / 2.0),
        egui::pos2(knob_x - knob_size / 2.0, center_y),
    ];
    if hover {
        // 辉光晕：两层半透明大菱形叠出 bloom。
        for (mul, alpha) in [(2.2_f32, 50_u8), (1.55_f32, 80_u8)] {
            let pts = vec![
                egui::pos2(knob_x, center_y - knob_size / 2.0 * mul),
                egui::pos2(knob_x + knob_size / 2.0 * mul, center_y),
                egui::pos2(knob_x, center_y + knob_size / 2.0 * mul),
                egui::pos2(knob_x - knob_size / 2.0 * mul, center_y),
            ];
            painter.add(egui::Shape::convex_polygon(
                pts,
                Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, alpha),
                egui::Stroke::NONE,
            ));
        }
    }
    painter.add(egui::Shape::convex_polygon(
        knob_pts,
        cyan,
        egui::Stroke::new(1.5, Color32::from_rgba_unmultiplied(255, 255, 255, 220)),
    ));

    // 鼠标拖动 → seek。点击 / 拖完都 commit；拖动过程中不发，避免 mpv 重定位刷屏。
    if resp.drag_stopped() || (resp.clicked() && !resp.is_pointer_button_down_on()) {
        if let Some(p) = resp.interact_pointer_pos() {
            let frac = ((p.x - rect.left()) / rect.width()).clamp(0.0, 1.0) as f64;
            actions.push(Action::Seek(frac * max));
        }
    }
}

/// 圆形 ghost 按钮：透明底 + hover 浅青描边 + hover 时辉光晕。给上下集 / 静音用。
fn draw_ghost_circle(
    ui: &mut egui::Ui,
    glyph: &str,
    tooltip: &str,
    enabled: bool,
    cyan: Color32,
    on_click: impl FnOnce(),
) {
    // 圆本身 34×34，但 allocate 一个 34×46 的槽位 —— 跟同行 draw_primary_circle
    // 高度对齐，圆在槽位中心绘制。原因：horizontal 行的高度由首个 widget 决定，
    // 后面的 widget 才按 Align::Center 居中；如果 ghost 用 34 高度先 allocate、
    // primary 再用 46 把行撑高，那"上一集"会贴行顶（首 widget 不会回头重对齐），
    // 而"下一集"已经按 46 居中——视觉上就是「左高右低」。统一槽位高度后所有
    // 控件都按 46 居中，没有时序问题。
    let circle_d = 34.0_f32;
    let row_h = 46.0_f32;
    let size = egui::vec2(circle_d, row_h);
    let (rect, resp) = ui.allocate_exact_size(
        size,
        if enabled {
            egui::Sense::click()
        } else {
            egui::Sense::hover()
        },
    );
    let resp = resp.on_hover_text(tooltip);
    let hovered = enabled && resp.hovered();
    let painter = ui.painter();
    // 圆心固定在槽位的几何中心；半径按 34 圆算。
    let center = rect.center();
    let r = circle_d / 2.0 - 1.0;
    if hovered {
        // 辉光晕：外圈半透明青色光圈。
        painter.circle_filled(
            center,
            r + 4.0,
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 40),
        );
    }
    let stroke_alpha = if hovered { 200 } else { 80 };
    painter.circle_stroke(
        center,
        r,
        egui::Stroke::new(
            1.2,
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, stroke_alpha),
        ),
    );
    let glyph_color = if !enabled {
        Color32::from_gray(85)
    } else if hovered {
        cyan
    } else {
        Color32::from_gray(225)
    };
    painter.text(
        center,
        egui::Align2::CENTER_CENTER,
        glyph,
        egui::FontId::proportional(13.0),
        glyph_color,
    );
    if enabled && resp.clicked() {
        on_click();
    }
}

/// 主按钮：实心青色大圆，带辉光晕，play/pause 中心焦点。
fn draw_primary_circle(
    ui: &mut egui::Ui,
    glyph: &str,
    cyan: Color32,
    on_click: impl FnOnce(),
) {
    let size = egui::vec2(46.0, 46.0);
    let (rect, resp) = ui.allocate_exact_size(size, egui::Sense::click());
    let center = rect.center();
    let r = size.x.min(size.y) / 2.0 - 1.0;
    let painter = ui.painter();
    let hovered = resp.hovered();

    // 外圈辉光：两层模糊光圈
    for (mul, alpha) in [(1.45_f32, if hovered { 90_u8 } else { 50 }),
                         (1.18_f32, if hovered { 140_u8 } else { 90 })] {
        painter.circle_filled(
            center,
            r * mul,
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, alpha),
        );
    }
    // 主体：青色实心 + 1px 白色高光环
    painter.circle_filled(center, r, cyan);
    painter.circle_stroke(
        center,
        r - 1.0,
        egui::Stroke::new(1.0, Color32::from_rgba_unmultiplied(255, 255, 255, 200)),
    );
    painter.text(
        center,
        egui::Align2::CENTER_CENTER,
        glyph,
        egui::FontId::proportional(18.0),
        Color32::from_rgb(8, 14, 20),
    );

    if resp.clicked() {
        on_click();
    }
}

/// 「芯片」按钮 — 矩形小标签，带斜切角和细描边，赛博 chip。
/// `active=true` 用青色实心填充（区别于普通态的透明 + 描边）。
fn draw_chip_button(
    ui: &mut egui::Ui,
    label: &str,
    cyan: Color32,
    active: bool,
    on_click: impl FnOnce(),
) {
    // 自己 measure label 长度后 allocate；icon-only 时强制最小宽 36px 让它
    // 看着不像孤伶伶的小方块。font 走 14px——比纯文字稍大一点，PUA 图标
    // 在小字号下细节会糊。
    let font = egui::FontId::proportional(14.0);
    let galley = ui.fonts(|f| f.layout_no_wrap(label.into(), font.clone(), Color32::WHITE));
    let pad = egui::vec2(12.0, 7.0);
    let measured = galley.size() + egui::vec2(pad.x * 2.0, pad.y * 2.0);
    let size = egui::vec2(measured.x.max(36.0), measured.y.max(30.0));
    let (rect, resp) = ui.allocate_exact_size(size, egui::Sense::click());
    let hovered = resp.hovered();
    let painter = ui.painter();

    let (fill, stroke_color, text_color) = if active {
        (cyan, cyan, Color32::from_rgb(8, 14, 20))
    } else if hovered {
        (
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 30),
            cyan,
            cyan,
        )
    } else {
        (
            Color32::TRANSPARENT,
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 90),
            Color32::from_gray(225),
        )
    };

    painter.rect_filled(rect, egui::CornerRadius::same(4), fill);
    painter.rect_stroke(
        rect,
        egui::CornerRadius::same(4),
        egui::Stroke::new(1.0, stroke_color),
        egui::StrokeKind::Inside,
    );
    painter.text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        label,
        font,
        text_color,
    );
    if resp.clicked() {
        on_click();
    }
}

/// 在线字幕搜索 / 预览 / 绑定面板。
///
/// 视觉：居中浮窗，约 560×600，黑底青边，跟底栏整体调性一致。
/// 行为：
///   - 关键词输入框 + 搜索按钮，回车也触发
///   - 状态行：Loading / 候选数 / Error / busy 提示 / last_message
///   - 滚动列表：每行 = 标题 + 来源/语言/格式 chip + [预览] [绑定] 两个按钮
///   - ✕ 关闭按钮（or Esc 由主循环处理；这里只负责派 CloseSubtitleSearch）
fn draw_subtitle_search_window(
    ctx: &egui::Context,
    state: &PlayerState,
    actions: &mut Vec<Action>,
    cyan: Color32,
    search_buf: &mut String,
) {
    // 复制一份在线状态快照，避免在 UI 渲染期间长时间持锁。
    let snapshot: (
        SearchPhase,
        Option<String>,
        Option<String>,
    ) = match state.online_search_state.lock() {
        Ok(g) => {
            // SearchPhase 不是 Clone（Vec<OnlineCandidate> 自带 Clone），手工克隆。
            let phase = match &g.search {
                SearchPhase::Idle => SearchPhase::Idle,
                SearchPhase::Loading => SearchPhase::Loading,
                SearchPhase::Loaded(v) => SearchPhase::Loaded(v.clone()),
                SearchPhase::Error(s) => SearchPhase::Error(s.clone()),
            };
            (phase, g.busy_candidate.clone(), g.last_message.clone())
        }
        Err(_) => (SearchPhase::Idle, None, None),
    };
    let (phase, busy_candidate, last_message) = snapshot;

    let frame = egui::Frame {
        fill: Color32::from_rgba_unmultiplied(8, 12, 18, 245),
        stroke: egui::Stroke::new(1.0, cyan.gamma_multiply(0.55)),
        corner_radius: egui::CornerRadius::same(8),
        inner_margin: egui::Margin::same(16),
        outer_margin: egui::Margin::ZERO,
        shadow: egui::epaint::Shadow {
            offset: [0, 8],
            blur: 24,
            spread: 0,
            color: Color32::from_black_alpha(180),
        },
    };

    let mut should_close = false;

    // 计算可用高度：上下各留 60px 边距，避免顶部被 Win11 标题栏裁、
    // 底部被任务栏裁。max_height 由屏幕实际尺寸推导，不写死。
    let screen = ctx.screen_rect();
    let avail_h = (screen.height() - 120.0).max(360.0);
    let win_h = avail_h.min(640.0);

    egui::Window::new("在线字幕搜索")
        .frame(frame)
        .title_bar(false)        // 自己画标题行 → 关闭 egui 默认 chrome
        .collapsible(false)
        .resizable(true)
        .default_width(620.0)
        .default_height(win_h)
        .min_height(360.0)
        .max_height(avail_h)
        .anchor(egui::Align2::CENTER_CENTER, egui::vec2(0.0, 0.0))
        .show(ctx, |ui| {
            // 标题行 + ✕ 关闭。手画 close 让样式跟其他 chip 一致。
            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new(format!("{} 在线字幕", icons::SUBTITLE))
                        .color(cyan)
                        .size(15.0)
                        .strong(),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.scope(|ui| {
                        install_chip_style(ui, cyan);
                        if ui.button("✕").clicked() {
                            should_close = true;
                        }
                    });
                });
            });
            ui.add_space(6.0);
            ui.separator();
            ui.add_space(8.0);

            // 关键词输入 + 搜索按钮。回车 = 搜索。
            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new("关键词")
                        .color(Color32::from_gray(180))
                        .size(12.0),
                );
                let resp = ui.add_sized(
                    egui::vec2(ui.available_width() - 96.0, 28.0),
                    egui::TextEdit::singleline(search_buf)
                        .hint_text("影片名 / 文件名"),
                );
                let triggered_enter = resp.lost_focus()
                    && ui.input(|i| i.key_pressed(egui::Key::Enter));
                ui.scope(|ui| {
                    install_chip_style(ui, cyan);
                    let btn = ui.button(
                        egui::RichText::new("搜索").color(Color32::from_gray(225)),
                    );
                    if btn.clicked() || triggered_enter {
                        if !search_buf.trim().is_empty() {
                            actions.push(Action::RunSubtitleSearch(
                                search_buf.trim().to_string(),
                            ));
                        }
                    }
                });
            });

            ui.add_space(8.0);

            // 状态行：phase + last_message
            match &phase {
                SearchPhase::Idle => {
                    ui.label(
                        egui::RichText::new("输入关键词后回车开始搜索。")
                            .color(Color32::from_gray(160))
                            .size(11.5),
                    );
                }
                SearchPhase::Loading => {
                    ui.label(
                        egui::RichText::new("正在搜索…")
                            .color(cyan)
                            .size(11.5),
                    );
                }
                SearchPhase::Loaded(items) => {
                    ui.label(
                        egui::RichText::new(format!("命中 {} 条候选", items.len()))
                            .color(Color32::from_gray(180))
                            .size(11.5),
                    );
                }
                SearchPhase::Error(msg) => {
                    ui.label(
                        egui::RichText::new(format!("错误：{msg}"))
                            .color(Color32::from_rgb(0xff, 0x6b, 0x6b))
                            .size(11.5),
                    );
                }
            }
            if let Some(msg) = &last_message {
                ui.label(
                    egui::RichText::new(msg)
                        .color(Color32::from_gray(170))
                        .italics()
                        .size(11.0),
                );
            }

            ui.add_space(8.0);

            // 候选列表
            if let SearchPhase::Loaded(items) = &phase {
                egui::ScrollArea::vertical()
                    .auto_shrink([false, true])
                    .show(ui, |ui| {
                        for item in items {
                            draw_candidate_row(ui, item, &busy_candidate, cyan, actions);
                        }
                    });
            }

            // 底部使用提示
            ui.add_space(6.0);
            ui.separator();
            ui.label(
                egui::RichText::new("「预览」会临时加载字幕、不持久化；觉得合适再点「绑定」。")
                    .color(Color32::from_gray(140))
                    .size(10.5),
            );
        });

    if should_close {
        actions.push(Action::CloseSubtitleSearch);
    }
}

fn draw_candidate_row(
    ui: &mut egui::Ui,
    item: &OnlineCandidate,
    busy_candidate: &Option<String>,
    cyan: Color32,
    actions: &mut Vec<Action>,
) {
    let busy = busy_candidate.as_deref() == Some(item.candidate_id.as_str());
    let frame = egui::Frame {
        fill: Color32::from_rgba_unmultiplied(255, 255, 255, 8),
        stroke: egui::Stroke::new(
            1.0,
            Color32::from_rgba_unmultiplied(255, 255, 255, 24),
        ),
        corner_radius: egui::CornerRadius::same(6),
        inner_margin: egui::Margin::same(10),
        outer_margin: egui::Margin {
            left: 0,
            right: 0,
            top: 0,
            bottom: 6,
        },
        shadow: egui::epaint::Shadow::NONE,
    };
    frame.show(ui, |ui| {
        // 用 right_to_left 整行布局：先把按钮塞进右侧、claim 它们要的宽度，
        // 剩下的空间留给左侧 vertical 文本块。这样长文件名 wrap 时不会
        // 跑到按钮下面 / 跟按钮重叠。
        ui.horizontal(|ui| {
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.scope(|ui| {
                    install_chip_style(ui, cyan);
                    let bind_btn = ui.add_enabled(
                        !busy,
                        egui::Button::new(
                            egui::RichText::new("绑定").color(Color32::from_gray(225)),
                        ),
                    );
                    if bind_btn.clicked() {
                        actions.push(Action::BindOnlineSubtitle {
                            candidate_id: item.candidate_id.clone(),
                            label: item.label.clone(),
                        });
                    }
                    ui.add_space(4.0);
                    let preview_btn = ui.add_enabled(
                        !busy,
                        egui::Button::new(
                            egui::RichText::new("预览").color(Color32::from_gray(225)),
                        ),
                    );
                    if preview_btn.clicked() {
                        actions.push(Action::PreviewOnlineSubtitle {
                            candidate_id: item.candidate_id.clone(),
                            label: item.label.clone(),
                        });
                    }
                    if busy {
                        ui.add_space(4.0);
                        ui.label(
                            egui::RichText::new("处理中…")
                                .color(cyan)
                                .size(11.0),
                        );
                    }

                    // 余下宽度给左侧文本块。allocate_ui_with_layout 在
                    // right_to_left 当前 cursor 之后留出"剩下的空间"给子 ui。
                    ui.add_space(8.0);
                    let remain = ui.available_width().max(120.0);
                    ui.allocate_ui_with_layout(
                        egui::vec2(remain, 0.0),
                        egui::Layout::top_down(egui::Align::LEFT),
                        |ui| {
                            // 强制 wrap 到容器宽度，否则长 release name 单行
                            // 撑开 horizontal 的总宽，把按钮顶出去。
                            ui.style_mut().wrap_mode = Some(egui::TextWrapMode::Wrap);
                            ui.label(
                                egui::RichText::new(&item.label)
                                    .color(Color32::from_gray(230))
                                    .size(12.5)
                                    .strong(),
                            );
                            let mut meta_parts: Vec<String> = Vec::new();
                            if !item.source.is_empty() {
                                meta_parts.push(item.source.clone());
                            }
                            if let Some(lang) = &item.language {
                                meta_parts.push(lang.clone());
                            }
                            if let Some(fmt) = &item.format {
                                meta_parts.push(fmt.to_uppercase());
                            }
                            if !meta_parts.is_empty() {
                                ui.label(
                                    egui::RichText::new(meta_parts.join(" · "))
                                        .color(Color32::from_gray(150))
                                        .size(11.0),
                                );
                            }
                        },
                    );
                });
            });
        });
    });
}

/// 字幕下拉：列表 = 「关闭字幕」 + 当前 resource 的 subtitles[] + mpv 内置的
/// sub track。点中后派发 SetSubtitle(Option<url>)。
/// mpv 一旦 sub-add 选中外挂，sid 会变；我们用 url 做唯一键比较干净。
fn draw_subtitle_menu(
    ui: &mut egui::Ui,
    state: &PlayerState,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    use egui::menu;
    let label = subtitle_button_label(state);
    // 触发按钮放在 scope 里 + install_chip_style，让样式跟旁边手画的 chip
    // 完全一致；scope 退出后 style 自动还原，不影响下拉里 menu_row 的渲染。
    ui.scope(|ui| {
        install_chip_style(ui, cyan);
        let _ = menu::menu_button(ui, pill_text(&label, cyan, false), |ui| {
        ui.set_min_width(280.0);

        // 「当前正在播放哪条字幕」靠 mpv 的 selected 字段反查：
        //   - kind==sub && selected=true 的轨就是当前轨
        //   - external==true 时，external_filename 就是当初 sub-add 用的 URL/路径，
        //     拿它去匹配「已绑定」段的 SubtitleMeta.url 或「临时预览」段的
        //     PreviewSub.tmp_path
        //   - external==false 时直接用 track.id 匹配「内嵌」段
        // mpv `sid` 属性也存了号，但外挂字幕在切集 / 反复 sub-add 后 sid 会跳，
        // external_filename 是稳定的字符串匹配，更可靠。
        let active_sub_track = state
            .tracks
            .iter()
            .find(|t| t.kind == "sub" && t.selected);
        let active_external_path = active_sub_track
            .filter(|t| t.external)
            .and_then(|t| t.external_filename.as_deref());
        let active_internal_id = active_sub_track
            .filter(|t| !t.external)
            .map(|t| t.id);
        // mpv 把 sid 设成 "no" 是「关闭字幕」的真值；track-list 没显式标这个。
        let off_active = matches!(state.current_sid.as_deref(), Some("no"))
            || active_sub_track.is_none();

        // 「关闭字幕」放在最顶上，不进 ScrollArea —— 用户最常用的"关掉一切
        // 字幕"应该常驻可见，不会被几十条内嵌 sub 推到下面。
        if menu_row(ui, "关闭字幕", off_active, cyan).clicked() {
            actions.push(Action::SetSubtitle(None));
            ui.close();
        }

        // 中段（三段：已绑定 → 内嵌 → 临时预览）放进 ScrollArea —— 蓝光原盘
        // 内嵌可能有 30+ 条多语种字幕，没滚动条会撑过屏幕，下面的「搜索在线
        // 字幕」按钮被推到屏幕外。max_height 540 给屏幕留底部安全距，配合
        // auto_shrink([false,true]) 让不满 540 时自动收紧。
        egui::ScrollArea::vertical()
            .max_height(540.0)
            .auto_shrink([false, true])
            .show(ui, |ui| {
                // 段 1：在线 · 已绑定 ——————————————————————————
                // 来源：state.movie.resources[i].subtitles[]，是后端持久化的字幕。
                // 显示顺序优先因为这是用户主动选过的「认准的」字幕，下次切集
                // 也还在；放最上面让用户最快找到。
                // 行内挂一个 ✕ 按钮 → 进二次确认态；二次确认时整行换成
                // 「确定 / 取消」红框。删除走 DELETE /resources/{id}/subtitles/{sid}。
                let bound: Vec<_> = state
                    .current_resource()
                    .map(|r| r.subtitles.iter().collect::<Vec<_>>())
                    .unwrap_or_default();
                if !bound.is_empty() {
                    section_header(ui, "在线字幕 · 已绑定", cyan);
                    for sub in bound {
                        // 后端 1.21+ 给的 display_name 是 release 标题（去扩展名），
                        // 比 label（"Chinese Simplified+English ASS (SubHD)"）和
                        // filename（带 hash 后缀）都更可读。优先用它。
                        let display = sub
                            .display_name
                            .clone()
                            .or_else(|| sub.label.clone())
                            .or_else(|| sub.format.clone())
                            .unwrap_or_else(|| sub.id.clone());
                        let active = active_external_path
                            .map(|p| p == sub.url)
                            .unwrap_or(false);
                        let pending = state
                            .pending_delete_sid
                            .as_deref()
                            == Some(sub.id.as_str());
                        if pending {
                            // 二次确认行：整行红框 + 「确定 / 取消」。整行点击
                            // = 取消（按钮命中优先，所以即便按钮在行 rect 里，
                            // 不会重复触发）。
                            let (row, confirm, cancel) = menu_row_confirm_delete(
                                ui, &display, cyan,
                            );
                            if confirm.clicked() {
                                actions.push(Action::ConfirmDeleteSubtitle(
                                    sub.id.clone(),
                                ));
                            } else if cancel.clicked() {
                                actions.push(Action::CancelDeleteSubtitle);
                            } else if row.clicked() {
                                actions.push(Action::CancelDeleteSubtitle);
                            }
                        } else {
                            let (row, del) = menu_row_with_danger_button(
                                ui,
                                &display,
                                active,
                                cyan,
                                icons::DELETE,
                            );
                            if del.clicked() {
                                actions.push(Action::RequestDeleteSubtitle(
                                    sub.id.clone(),
                                ));
                            } else if row.clicked() {
                                actions.push(Action::SetSubtitle(Some(
                                    sub.url.clone(),
                                )));
                                ui.close();
                            }
                        }
                    }
                }

                // 段 2：内嵌 ————————————————————————————————
                // 来源：mpv track-list 里 kind=="sub" 且 external=false 的轨。
                // 蓝光 / mkv 自带的字幕全在这里。
                let internal: Vec<_> = state
                    .tracks
                    .iter()
                    .filter(|t| t.kind == "sub" && !t.external)
                    .collect();
                if !internal.is_empty() {
                    section_header(ui, "内嵌字幕", cyan);
                    for t in internal {
                        let display = t
                            .title
                            .clone()
                            .or_else(|| t.lang.clone())
                            .unwrap_or_else(|| format!("内嵌 #{}", t.id));
                        let active = active_internal_id == Some(t.id);
                        if menu_row(ui, &display, active, cyan).clicked() {
                            actions.push(Action::SetSubtitleTrack(t.id));
                            ui.close();
                        }
                    }
                }

                // 段 3：在线 · 临时预览 —————————————————————————
                // 来源：state.preview_subtitles —— 用户在「搜索在线字幕」面板
                // 里点过预览的候选。生命周期 = 当前播放器进程；切集 / 退出后
                // 丢弃。空时整段不渲染（包括 header），免得平白多一条空标题。
                // 当前正在预览的那一行右侧挂个「绑定」小按钮 —— 用户觉得字幕
                // 合适直接绑定持久化，不用再翻搜索面板。
                if !state.preview_subtitles.is_empty() {
                    section_header(ui, "在线字幕 · 临时预览", cyan);
                    for prev in &state.preview_subtitles {
                        let active = active_external_path
                            .map(|p| p == prev.tmp_path)
                            .unwrap_or(false);
                        if active {
                            // 正在播 = 才有「绑定」按钮（其它预览条目说明已经
                            // 被切走，再绑定意味着自动切回它，太突兀；先要求
                            // 用户点中→预览→播 → 看合适→绑定，路径单一）。
                            let (row, btn) = menu_row_with_button(
                                ui,
                                &prev.label,
                                true,
                                cyan,
                                "绑定",
                            );
                            if btn.clicked() {
                                actions.push(Action::BindOnlineSubtitle {
                                    candidate_id: prev.candidate_id.clone(),
                                    label: prev.label.clone(),
                                });
                                ui.close();
                            } else if row.clicked() {
                                // 已经在播这条字幕，再点等同于"无操作"——但保
                                // 留让 mpv 重新 select 一次，万一字幕轨道被
                                // 别的操作切走也能回来。
                                actions.push(Action::SetSubtitle(Some(
                                    prev.tmp_path.clone(),
                                )));
                                ui.close();
                            }
                        } else if menu_row(ui, &prev.label, false, cyan).clicked() {
                            // 未在播的预览条目：点击 = sub-add+select 切回它。
                            actions.push(Action::SetSubtitle(Some(
                                prev.tmp_path.clone(),
                            )));
                            ui.close();
                        }
                    }
                }

                // 段 4：在线 · 搜索结果（候选） —————————————————
                // 来源：state.online_search_state.search 里 Loaded 的候选；
                // 排除已经在「临时预览」段里出现过的（避免重复）。点击 =
                // 触发预览（走 Action::PreviewOnlineSubtitle），跑完以后该条
                // 候选会从这一段消失、出现在第 3 段并自动播放。这样用户在
                // 同一个下拉里就能"看效果不行 → 换一条 → 满意 → 绑定"，
                // 不用反复弹出搜索面板。
                let candidates: Vec<crate::native_player::controller::OnlineCandidate> = state
                    .online_search_state
                    .lock()
                    .ok()
                    .and_then(|g| match &g.search {
                        crate::native_player::controller::SearchPhase::Loaded(items) => {
                            Some(items.clone())
                        }
                        _ => None,
                    })
                    .unwrap_or_default();
                let busy_cid: Option<String> = state
                    .online_search_state
                    .lock()
                    .ok()
                    .and_then(|g| g.busy_candidate.clone());
                let unpreviewed: Vec<_> = candidates
                    .iter()
                    .filter(|c| {
                        !state
                            .preview_subtitles
                            .iter()
                            .any(|p| p.candidate_id == c.candidate_id)
                    })
                    .collect();
                if !unpreviewed.is_empty() {
                    section_header(ui, "在线字幕 · 搜索结果（点击预览）", cyan);
                    for c in unpreviewed {
                        let busy = busy_cid.as_deref() == Some(c.candidate_id.as_str());
                        let display = if busy {
                            format!("⏳ {}", c.label)
                        } else {
                            c.label.clone()
                        };
                        if menu_row(ui, &display, false, cyan).clicked() && !busy {
                            actions.push(Action::PreviewOnlineSubtitle {
                                candidate_id: c.candidate_id.clone(),
                                label: c.label.clone(),
                            });
                            // 不 ui.close()：用户多半要继续在菜单里换字幕看
                            // 哪条合适，关掉再开一次反而打断决策流。
                        }
                    }
                }
            });

        // 搜索在线字幕入口 —— 永远在最底（ScrollArea 之外），用户找得到。
        ui.separator();
        let search_resp = menu_row(
            ui,
            &format!("{} 搜索在线字幕…", icons::SUBTITLE),
            false,
            cyan,
        );
        if search_resp.clicked() {
            actions.push(Action::OpenSubtitleSearch);
            ui.close();
        }
        });
    });
}

/// 字幕菜单的小节标题：青色弱化文字，配上下分隔线把不同来源段视觉切开。
/// 用 ui.label + manual separator 而不是 ui.collapsing/heading —— 我们不想要
/// 折叠箭头或大字号，纯粹是个分组提示。
fn section_header(ui: &mut egui::Ui, text: &str, cyan: Color32) {
    ui.add_space(2.0);
    ui.separator();
    ui.add_space(2.0);
    // header 文字用 cyan 70% 亮度 + 11px size + 字间距让它看起来像 chapter title
    // 而不是可点击行；前面留 12px 内边距对齐 menu_row 的 text_pos。
    let avail_w = ui.available_width();
    let (rect, _) = ui.allocate_exact_size(
        egui::vec2(avail_w, 18.0),
        egui::Sense::hover(),
    );
    let painter = ui.painter();
    let dim_cyan = Color32::from_rgba_unmultiplied(
        cyan.r(),
        cyan.g(),
        cyan.b(),
        180,
    );
    painter.text(
        egui::pos2(rect.left() + 12.0, rect.center().y),
        egui::Align2::LEFT_CENTER,
        text,
        egui::FontId::proportional(11.5),
        dim_cyan,
    );
    ui.add_space(2.0);
}

fn subtitle_button_label(state: &PlayerState) -> String {
    // 只显示「图标 + (N)」+ 下拉箭头；选中具体字幕也不挂文字 — 文字会让按钮
    // 一下变得很长很丑，用户从 hover tooltip 或下拉里看明细就够。
    // 计数 (N) 留下来，因为这是用户判断"字幕有没有对接到"的唯一信号；
    // 三段来源（已绑定 / 内嵌 / 临时预览）都算进去，跟下拉里的总条数对得上。
    let bound_count = state
        .current_resource()
        .map(|r| r.subtitles.len())
        .unwrap_or(0);
    let int_count = state
        .tracks
        .iter()
        .filter(|t| t.kind == "sub" && !t.external)
        .count();
    let preview_count = state.preview_subtitles.len();
    let total = bound_count + int_count + preview_count;
    if total > 0 {
        format!("{} ({total}) {}", icons::SUBTITLE, icons::CHEVRON_DOWN)
    } else {
        format!("{} {}", icons::SUBTITLE, icons::CHEVRON_DOWN)
    }
}

/// 音轨下拉：从 mpv track-list 拉 audio 类。aid="no" 当作禁音，几乎不会出现。
fn draw_audio_menu(
    ui: &mut egui::Ui,
    state: &PlayerState,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    use egui::menu;
    let label = audio_button_label(state);
    ui.scope(|ui| {
        install_chip_style(ui, cyan);
        let _ = menu::menu_button(ui, pill_text(&label, cyan, false), |ui| {
        ui.set_min_width(220.0);
        let audios: Vec<_> = state.audio_tracks().collect();
        if audios.is_empty() {
            ui.label(
                egui::RichText::new("（无音轨信息）").color(Color32::from_gray(140)),
            );
            return;
        }
        for t in audios {
            let display = t
                .title
                .clone()
                .or_else(|| t.lang.clone())
                .or_else(|| t.codec.clone())
                .unwrap_or_else(|| format!("音轨 #{}", t.id));
            let row_label = format!("#{} · {display}", t.id);
            if menu_row(ui, &row_label, t.selected, cyan).clicked() {
                actions.push(Action::SetAudioTrack(t.id));
                ui.close();
            }
        }
        });
    });
}

fn audio_button_label(_state: &PlayerState) -> String {
    // 同 subtitle —— 只留图标 + 箭头。具体在哪条轨上从下拉菜单里看，按钮
    // 上不挂文本（"音轨·en" 这种短码看着像 chip 上贴胶布）。
    format!("{} {}", icons::AUDIO, icons::CHEVRON_DOWN)
}

/// 倍速下拉：固定 5 档（0.5/1.0/1.25/1.5/2.0），选中时加 ✓ 标记。
fn draw_speed_menu(
    ui: &mut egui::Ui,
    state: &PlayerState,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    use egui::menu;
    let label = format!("{:.2}x {}", state.speed.max(0.01), icons::CHEVRON_DOWN);
    ui.scope(|ui| {
        install_chip_style(ui, cyan);
        let _ = menu::menu_button(ui, pill_text(&label, cyan, false), |ui| {
        ui.set_min_width(140.0);
        for s in [0.5, 1.0, 1.25, 1.5, 2.0] {
            let active = (state.speed - s).abs() < 0.01;
            let row_label = format!("{:.2}x", s);
            if menu_row(ui, &row_label, active, cyan).clicked() {
                actions.push(Action::SetSpeed(s));
                ui.close();
            }
        }
        });
    });
}

/// 下拉行：通用样式 — 选中时左侧加青色 ✓，hover 灰底。返回 Response 给调用方
/// 判断 click。
/// 下拉行：通用样式 — 选中时左侧加青色 ✓，hover 浅青底+青字。返回 Response 给调用方
/// 判断 click。手画 hover 而不是用 egui::Button(frame=true) —— Button 的默认描边
/// 在下拉里会把每行画成独立按钮，看着碎；我们要 web list-item 那种整行高亮。
fn menu_row(
    ui: &mut egui::Ui,
    label: &str,
    active: bool,
    cyan: Color32,
) -> egui::Response {
    let (resp, _) = menu_row_inner(ui, label, active, cyan, None);
    resp
}

/// 带行内按钮的版本：右侧画一个 chip 风格小按钮，行点击 = 主操作（如预览），
/// 按钮点击 = 副操作（如绑定）。返回 (row_resp, Some(button_resp))。
/// 调用方先判断 button.clicked，再判断 row.clicked，避免命中按钮区域时
/// 行同时触发双动作。
fn menu_row_with_button(
    ui: &mut egui::Ui,
    label: &str,
    active: bool,
    cyan: Color32,
    button_label: &str,
) -> (egui::Response, egui::Response) {
    let (row, btn) = menu_row_inner_styled(
        ui,
        label,
        active,
        cyan,
        Some(button_label),
        false,
    );
    (row, btn.expect("right button requested"))
}

/// 跟 `menu_row_with_button` 同款，但按钮渲染成「危险」配色（透明底 + 红 hover），
/// 用于已绑定字幕行右侧的删除 ✕。
fn menu_row_with_danger_button(
    ui: &mut egui::Ui,
    label: &str,
    active: bool,
    cyan: Color32,
    button_label: &str,
) -> (egui::Response, egui::Response) {
    let (row, btn) = menu_row_inner_styled(
        ui,
        label,
        active,
        cyan,
        Some(button_label),
        true,
    );
    (row, btn.expect("right button requested"))
}

/// menu_row 的实际渲染实现 —— button_label 为 None 时不画按钮、第二个返回值为 None。
fn menu_row_inner(
    ui: &mut egui::Ui,
    label: &str,
    active: bool,
    cyan: Color32,
    button_label: Option<&str>,
) -> (egui::Response, Option<egui::Response>) {
    menu_row_inner_styled(ui, label, active, cyan, button_label, false)
}

/// 二次确认行 —— 行内挂两个按钮：「确定」(红警示色) + 「取消」(灰)。整行点击
/// 视为取消。返回 (row, confirm, cancel)。
fn menu_row_confirm_delete(
    ui: &mut egui::Ui,
    label: &str,
    cyan: Color32,
) -> (egui::Response, egui::Response, egui::Response) {
    let avail_w = ui.available_width();
    let row_h = 28.0_f32;
    let (rect, row_resp) = ui.allocate_exact_size(
        egui::vec2(avail_w, row_h),
        egui::Sense::click(),
    );
    let painter = ui.painter().clone();
    // 整行用警示色淡底，让二次确认态在视觉上跟普通行明显区分。
    painter.rect_filled(
        rect,
        egui::CornerRadius::same(3),
        Color32::from_rgba_unmultiplied(0xef, 0x44, 0x44, 22),
    );

    // 两个按钮从右往左排：取消(48) → 确定(48)，间距 6。
    let btn_w = 48.0;
    let btn_h = 20.0;
    let cancel_rect = egui::Rect::from_min_size(
        egui::pos2(
            rect.right() - btn_w - 8.0,
            rect.center().y - btn_h / 2.0,
        ),
        egui::vec2(btn_w, btn_h),
    );
    let confirm_rect = egui::Rect::from_min_size(
        egui::pos2(
            cancel_rect.left() - btn_w - 6.0,
            rect.center().y - btn_h / 2.0,
        ),
        egui::vec2(btn_w, btn_h),
    );

    let confirm_id = ui.id().with(label).with("__confirm_btn");
    let cancel_id = ui.id().with(label).with("__cancel_btn");
    let confirm_resp = ui.interact(confirm_rect, confirm_id, egui::Sense::click());
    let cancel_resp = ui.interact(cancel_rect, cancel_id, egui::Sense::click());

    // 确定 = 实心红
    let red = Color32::from_rgb(0xef, 0x44, 0x44);
    let confirm_bg = if confirm_resp.hovered() {
        red
    } else {
        Color32::from_rgba_unmultiplied(0xef, 0x44, 0x44, 100)
    };
    let confirm_fg = if confirm_resp.hovered() {
        Color32::WHITE
    } else {
        Color32::from_rgba_unmultiplied(0xff, 0xe0, 0xe0, 255)
    };
    painter.rect_filled(confirm_rect, egui::CornerRadius::same(3), confirm_bg);
    painter.text(
        confirm_rect.center(),
        egui::Align2::CENTER_CENTER,
        "确定",
        egui::FontId::proportional(11.0),
        confirm_fg,
    );

    // 取消 = ghost (青描边)
    let cancel_bg = if cancel_resp.hovered() {
        Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 60)
    } else {
        Color32::TRANSPARENT
    };
    let cancel_fg = if cancel_resp.hovered() {
        cyan
    } else {
        Color32::from_gray(220)
    };
    painter.rect_filled(cancel_rect, egui::CornerRadius::same(3), cancel_bg);
    painter.rect_stroke(
        cancel_rect,
        egui::CornerRadius::same(3),
        egui::Stroke::new(
            1.0,
            Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 110),
        ),
        egui::StrokeKind::Outside,
    );
    painter.text(
        cancel_rect.center(),
        egui::Align2::CENTER_CENTER,
        "取消",
        egui::FontId::proportional(11.0),
        cancel_fg,
    );

    // 左侧 label —— 截断省略号，跟 menu_row_inner 一致。
    let label_left = rect.left() + 12.0;
    let max_text_width = (confirm_rect.left() - label_left - 8.0).max(40.0);
    let mut job = egui::text::LayoutJob::single_section(
        format!("删除「{label}」?"),
        egui::TextFormat {
            font_id: egui::FontId::proportional(12.5),
            color: Color32::from_rgb(0xff, 0xc8, 0xc8),
            ..Default::default()
        },
    );
    job.wrap.max_width = max_text_width;
    job.wrap.max_rows = 1;
    job.wrap.break_anywhere = true;
    let galley = ui.fonts(|f| f.layout_job(job));
    let text_y = rect.center().y - galley.size().y / 2.0;
    painter.galley(
        egui::pos2(label_left, text_y),
        galley,
        Color32::from_rgb(0xff, 0xc8, 0xc8),
    );

    (row_resp, confirm_resp, cancel_resp)
}

fn menu_row_inner_styled(
    ui: &mut egui::Ui,
    label: &str,
    active: bool,
    cyan: Color32,
    button_label: Option<&str>,
    button_danger: bool,
) -> (egui::Response, Option<egui::Response>) {
    // 整行 allocate：宽 = 当前 ui 可用宽，避免 hover 高亮宽窄不一。行高 26
    // 给按钮（20px）留 3px 上下间距，太矮会让 hover 高亮看着憋。
    let avail_w = ui.available_width();
    let row_h = if button_label.is_some() { 28.0 } else { 24.0 };
    let (rect, resp) = ui.allocate_exact_size(
        egui::vec2(avail_w, row_h),
        egui::Sense::click(),
    );
    let hovered = resp.hovered();

    let bg = if active {
        Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 28)
    } else if hovered {
        Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 18)
    } else {
        Color32::TRANSPARENT
    };
    let text_color = if active || hovered {
        cyan
    } else {
        Color32::from_gray(220)
    };

    let painter = ui.painter().clone();
    painter.rect_filled(rect, egui::CornerRadius::same(3), bg);
    // 选中时左侧 2px 青色指示条，比 ✓ 字符更直观。
    if active {
        painter.rect_filled(
            egui::Rect::from_min_max(
                egui::pos2(rect.left(), rect.top() + 4.0),
                egui::pos2(rect.left() + 2.0, rect.bottom() - 4.0),
            ),
            egui::CornerRadius::same(1),
            cyan,
        );
    }

    // 右侧按钮：先画 / 先 interact，把它的 rect 让出去，避免文字盖到上面。
    // 用 ui.interact 而不是 button —— 我们要自己手画样式跟下拉行的青色风
    // 格融在一起，egui::Button 默认 padding 太大、stroke 在多行下拉里看
    // 着像异物。
    let (btn_resp, btn_left) = if let Some(btn_text) = button_label {
        // danger 模式（删除按钮）= 24×20 方块、只放一个图标；普通模式 = 48×20，
        // 放短文本（如「绑定」）。删除做小一点不抢主操作的视觉权重。
        let (btn_w, btn_h) = if button_danger {
            (24.0_f32, 20.0_f32)
        } else {
            (48.0_f32, 20.0_f32)
        };
        let btn_rect = egui::Rect::from_min_size(
            egui::pos2(rect.right() - btn_w - 8.0, rect.center().y - btn_h / 2.0),
            egui::vec2(btn_w, btn_h),
        );
        let btn_id = ui.id().with(label).with("__row_btn");
        let br = ui.interact(btn_rect, btn_id, egui::Sense::click());
        let btn_hover = br.hovered();
        // 普通按钮：青底 cyan-on-cyan；danger 按钮：透明底 + 红 hover，
        // 让用户没刻意去点的时候看起来弱化、点上去才"火起来"。
        let (btn_bg, btn_fg) = if button_danger {
            let red = Color32::from_rgb(0xef, 0x44, 0x44);
            if btn_hover {
                (
                    Color32::from_rgba_unmultiplied(0xef, 0x44, 0x44, 60),
                    red,
                )
            } else {
                (Color32::TRANSPARENT, Color32::from_gray(160))
            }
        } else if btn_hover {
            (cyan, Color32::from_rgb(8, 10, 14))
        } else {
            (
                Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 80),
                cyan,
            )
        };
        painter.rect_filled(btn_rect, egui::CornerRadius::same(3), btn_bg);
        painter.text(
            btn_rect.center(),
            egui::Align2::CENTER_CENTER,
            btn_text,
            egui::FontId::proportional(11.0),
            btn_fg,
        );
        (Some(br), btn_rect.left())
    } else {
        (None, rect.right() - 8.0)
    };

    // Label —— 用 LayoutJob 单行 + max_width 自动 ellipsis 截断；painter.text
    // 没有截断能力，长片名（"阿凡达3：火与烬 [中&英]Avatar.Fire.and.Ash..."）
    // 会糊出菜单边界。max_rows=1 + break_anywhere=true 是 egui 0.32 的"单行
    // 截断带省略号"标准姿势。
    let label_left = rect.left() + 12.0;
    let max_text_width = (btn_left - label_left - 8.0).max(40.0);
    let mut job = egui::text::LayoutJob::single_section(
        label.to_string(),
        egui::TextFormat {
            font_id: egui::FontId::proportional(12.5),
            color: text_color,
            ..Default::default()
        },
    );
    job.wrap.max_width = max_text_width;
    job.wrap.max_rows = 1;
    job.wrap.break_anywhere = true;
    let galley = ui.fonts(|f| f.layout_job(job));
    let text_y = rect.center().y - galley.size().y / 2.0;
    painter.galley(
        egui::pos2(label_left, text_y),
        galley,
        text_color,
    );

    (resp, btn_resp)
}

/// pill 按钮的 RichText 包装 —— 给 menu_button 的触发器用。
/// 颜色统一：跟 chip 按钮的非选中态保持一致（gray225），别用纯白。
fn pill_text(label: &str, _cyan: Color32, _primary: bool) -> egui::RichText {
    egui::RichText::new(label)
        .color(Color32::from_gray(225))
        .size(14.0)
}

/// 把 chip 视觉（青色细描边 + 透明底 + hover 浅青亮）注入当前 ui 的 style，
/// 这样紧接着调用 menu::menu_button(ui, ...) 弹出的触发按钮就会跟旁边
/// 手画的 chip 长得一样。封装成单独函数避免 4 处复制。
fn install_chip_style(ui: &mut egui::Ui, cyan: Color32) {
    let v = &mut ui.style_mut().visuals.widgets;
    let stroke_idle = egui::Stroke::new(
        1.0,
        Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 90),
    );
    let stroke_hover = egui::Stroke::new(1.0, cyan);
    let bg_idle = Color32::TRANSPARENT;
    let bg_hover = Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 30);
    let bg_active = Color32::from_rgba_unmultiplied(0x22, 0xd3, 0xee, 50);
    let text_idle = Color32::from_gray(225);
    let text_hover = cyan;

    let r4 = egui::CornerRadius::same(4);
    v.inactive.bg_fill = bg_idle;
    v.inactive.weak_bg_fill = bg_idle;
    v.inactive.bg_stroke = stroke_idle;
    v.inactive.fg_stroke = egui::Stroke::new(1.0, text_idle);
    v.inactive.corner_radius = r4;
    v.hovered.bg_fill = bg_hover;
    v.hovered.weak_bg_fill = bg_hover;
    v.hovered.bg_stroke = stroke_hover;
    v.hovered.fg_stroke = egui::Stroke::new(1.0, text_hover);
    v.hovered.corner_radius = r4;
    v.active.bg_fill = bg_active;
    v.active.weak_bg_fill = bg_active;
    v.active.bg_stroke = stroke_hover;
    v.active.fg_stroke = egui::Stroke::new(1.0, text_hover);
    v.active.corner_radius = r4;
    v.open.bg_fill = bg_active;
    v.open.weak_bg_fill = bg_active;
    v.open.bg_stroke = stroke_hover;
    v.open.fg_stroke = egui::Stroke::new(1.0, text_hover);
    v.open.corner_radius = r4;
    // 顺手把按钮内边距调成 chip 风格 —— egui 默认是 (4,2) 偏紧。
    ui.spacing_mut().button_padding = egui::vec2(12.0, 7.0);
}

/// 胶囊按钮：青色边 + 透明底；激活态填青色背景。M3.6 第一稿用，等用户拍板视觉再调。
fn draw_pill_button(
    ui: &mut egui::Ui,
    label: &str,
    cyan: Color32,
    primary: bool,
    on_click: impl FnOnce(),
) {
    let (fill, text_color, stroke) = if primary {
        (
            cyan.gamma_multiply(0.18),
            cyan,
            egui::Stroke::new(1.0, cyan.gamma_multiply(0.7)),
        )
    } else {
        (
            Color32::from_rgba_unmultiplied(255, 255, 255, 14),
            Color32::from_gray(220),
            egui::Stroke::new(1.0, Color32::from_rgba_unmultiplied(255, 255, 255, 30)),
        )
    };
    let resp = egui::Frame::default()
        .fill(fill)
        .stroke(stroke)
        .corner_radius(egui::CornerRadius::same(6))
        .inner_margin(egui::Margin {
            left: 14,
            right: 14,
            top: 6,
            bottom: 6,
        })
        .show(ui, |ui| {
            ui.label(
                egui::RichText::new(label)
                    .color(text_color)
                    .size(12.0)
                    .strong(),
            );
        });
    let interact = ui.interact(
        resp.response.rect,
        ui.id().with(("pill", label)),
        egui::Sense::click(),
    );
    if interact.clicked() {
        on_click();
    }
}

/// 右侧详情面板：影片标题 + 当前集 + 集数网格 + 多源切换。
/// 视觉参考 web Player.tsx 的 350px 黑底面板。
fn draw_details_panel(
    ui: &mut egui::Ui,
    state: &PlayerState,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    let movie = match state.movie.as_ref() {
        Some(m) => m,
        None => {
            ui.add_space(16.0);
            ui.vertical_centered(|ui| {
                ui.label(
                    egui::RichText::new(if state.filename.is_empty() {
                        "正在加载..."
                    } else {
                        &state.filename
                    })
                    .color(Color32::from_gray(180)),
                );
            });
            return;
        }
    };

    // ---- 标题区 ----------------------------------------------------
    egui::Frame::default()
        .inner_margin(egui::Margin {
            left: 18,
            right: 18,
            top: 18,
            bottom: 14,
        })
        .show(ui, |ui| {
            ui.label(
                egui::RichText::new(&movie.title)
                    .color(Color32::WHITE)
                    .size(17.0)
                    .strong(),
            );
            // 副标题：原片名 / 年份 一行
            ui.horizontal_wrapped(|ui| {
                if let Some(orig) = movie
                    .original_title
                    .as_ref()
                    .filter(|s| !s.is_empty() && **s != movie.title)
                {
                    ui.label(
                        egui::RichText::new(orig)
                            .color(Color32::from_gray(140))
                            .size(11.0),
                    );
                }
                if let Some(year) = movie.year {
                    ui.label(
                        egui::RichText::new(format!("· {year}"))
                            .color(Color32::from_gray(120))
                            .size(11.0),
                    );
                }
            });
        });

    // 标题区下分隔线
    ui.painter().hline(
        ui.max_rect().x_range(),
        ui.cursor().min.y,
        egui::Stroke::new(
            1.0,
            Color32::from_rgba_unmultiplied(255, 255, 255, 18),
        ),
    );

    // ---- 季 tab 行（仅当后端给了 ≥ 2 个 seasons）----------------
    // effective_season 决定 episode grid 应该过滤哪些 resource_ids。
    // 优先级：state.active_season > 当前播放资源所在的季 > seasons[0]
    let effective_season: Option<i32> = if movie.seasons.len() >= 2 {
        state
            .active_season
            .or_else(|| {
                let cur = state.current_resource_id.as_deref()?;
                movie
                    .seasons
                    .iter()
                    .find(|sg| sg.resource_ids.iter().any(|id| id == cur))
                    .map(|sg| sg.season)
            })
            .or_else(|| movie.seasons.first().map(|sg| sg.season))
    } else {
        None
    };

    if movie.seasons.len() >= 2 {
        // 多季用 ComboBox（下拉单选）而不是 horizontal_wrapped tab。
        // 面板只有 280–350px 宽，超过 4 季就会换行成乱七八糟的方阵；
        // web 端能放横向滚动 + 「更多」抽屉是因为有 2/3 屏宽，PC 这边不行。
        // 单行下拉一次到位：当前季高亮，点开是完整列表，行内带「当前播放」
        // 标记（▶ 三角符），跟 web 端 isPlaying 同款语义。
        let active_label = movie
            .seasons
            .iter()
            .find(|sg| Some(sg.season) == effective_season)
            .map(|sg| sg.display_title.clone())
            .unwrap_or_else(|| "选择季".to_string());
        let playing_season = state
            .current_resource_id
            .as_deref()
            .and_then(|cur| {
                movie
                    .seasons
                    .iter()
                    .find(|sg| sg.resource_ids.iter().any(|id| id == cur))
                    .map(|sg| sg.season)
            });
        egui::Frame::default()
            .inner_margin(egui::Margin {
                left: 14,
                right: 14,
                top: 10,
                bottom: 10,
            })
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    egui::ComboBox::from_id_salt("season_picker")
                        .width(ui.available_width() - 4.0)
                        .selected_text(
                            egui::RichText::new(&active_label).color(cyan).size(12.0),
                        )
                        .show_ui(ui, |ui| {
                            ui.set_min_width(180.0);
                            for sg in &movie.seasons {
                                let is_active = effective_season == Some(sg.season);
                                let is_playing = playing_season == Some(sg.season);
                                let line_color = if is_playing {
                                    cyan
                                } else if is_active {
                                    Color32::WHITE
                                } else {
                                    Color32::from_gray(200)
                                };
                                let prefix = if is_playing { "▶ " } else { "   " };
                                let resp = ui.selectable_label(
                                    is_active,
                                    egui::RichText::new(format!(
                                        "{prefix}{}",
                                        sg.display_title
                                    ))
                                    .color(line_color)
                                    .size(12.0),
                                );
                                if resp.clicked() && !is_active {
                                    actions.push(Action::SetSeason(sg.season));
                                }
                            }
                        });
                });
            });
        ui.painter().hline(
            ui.max_rect().x_range(),
            ui.cursor().min.y,
            egui::Stroke::new(
                1.0,
                Color32::from_rgba_unmultiplied(255, 255, 255, 12),
            ),
        );
    }

    // ---- 集数 / 多源（滚动）-----------------------------------
    // 关键：side_panel 的可用宽度（panel_w - 滚动条预留 ~16px）必须显式
    // 传给 ScrollArea 内的子 ui，否则 ScrollArea 会把水平方向算成无界，
    // 内部的 horizontal_wrapped / Label::wrap 拿不到 wrap 边界，badge /
    // 文件名就直接溢出 panel 右边沿。`max_width` + 内层 set_width 双锁。
    let panel_inner_w = (ui.available_width() - 16.0).max(60.0);
    egui::ScrollArea::vertical()
        .auto_shrink([false; 2])
        .max_width(panel_inner_w)
        .show(ui, |ui| {
            ui.set_width(panel_inner_w);
            egui::Frame::default()
                .inner_margin(egui::Margin {
                    left: 14,
                    right: 14,
                    top: 14,
                    bottom: 14,
                })
                .show(ui, |ui| {
                    draw_resource_groups(ui, state, movie, effective_season, actions, cyan);
                });
        });
}

/// 把 resources 按 episode 分组：同一集的多个画质合到一起，按集数排列；
/// 单集 / 多集都用同一份代码。本函数布局：
///   - 多集 ≥ 2：5 列方块网格，每个方块显示集数；当前播放集高亮
///     方块下方展开「源切换」列表
///   - 单集（电影 / 标准内容）：直接铺平显示「源切换」列表
fn draw_resource_groups(
    ui: &mut egui::Ui,
    state: &PlayerState,
    movie: &crate::native_player::meta::MovieMeta,
    season_filter: Option<i32>,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    if movie.resources.is_empty() {
        ui.label(
            egui::RichText::new("没有可播放的资源")
                .color(Color32::from_gray(120))
                .italics(),
        );
        return;
    }

    // 当 effective_season 有值时，先用对应 SeasonMeta.resource_ids 把
    // movie.resources 限定到那一季——其余季的资源在网格里直接消失。
    // 没匹配到 season（比如电影、只有 standalone 组）就不过滤。
    let allowed_ids: Option<std::collections::HashSet<&str>> = season_filter.and_then(|s| {
        movie.seasons.iter().find(|sg| sg.season == s).map(|sg| {
            sg.resource_ids
                .iter()
                .map(|id| id.as_str())
                .collect::<std::collections::HashSet<_>>()
        })
    });
    let filtered: Vec<&crate::native_player::meta::ResourceMeta> = match &allowed_ids {
        Some(set) => movie
            .resources
            .iter()
            .filter(|r| set.contains(r.id.as_str()))
            .collect(),
        None => movie.resources.iter().collect(),
    };
    if filtered.is_empty() {
        ui.label(
            egui::RichText::new("当前季没有可播放的资源")
                .color(Color32::from_gray(120))
                .italics(),
        );
        return;
    }

    // 按 episode 标签分组（None 也就是单文件电影会进 "movie" 分组）
    use std::collections::BTreeMap;
    let mut groups: BTreeMap<EpKey, Vec<&crate::native_player::meta::ResourceMeta>> =
        BTreeMap::new();
    for r in &filtered {
        let key = match r.episode.as_deref() {
            None | Some("") => EpKey::Movie,
            Some(s) => match s.parse::<i32>() {
                Ok(n) => EpKey::Number(n),
                Err(_) => EpKey::Label(s.to_string()),
            },
        };
        groups.entry(key).or_default().push(*r);
    }

    let total = groups.len();
    let active_id = state.current_resource_id.as_deref();

    // ---- 集数标题 ----
    ui.horizontal(|ui| {
        ui.label(
            egui::RichText::new(if total == 1 { "正片" } else { "剧集" })
                .color(Color32::from_gray(180))
                .size(11.0)
                .strong(),
        );
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            ui.label(
                egui::RichText::new(format!("{total} 项"))
                    .color(Color32::from_gray(120))
                    .size(10.0)
                    .monospace(),
            );
        });
    });
    ui.add_space(10.0);

    if total == 1 {
        // 单集 / 电影：直接列出源
        if let Some((_k, sources)) = groups.iter().next() {
            for src in sources {
                draw_source_row(ui, src, active_id == Some(src.id.as_str()), actions, cyan);
                ui.add_space(8.0);
            }
        }
        return;
    }

    // ---- 集数方块网格（5 列）----
    let cols = 5usize;
    // egui ScrollArea 会在右侧自己塞滚动条，但 available_width() 不一定
    // 帮我们扣掉那点宽度——结果就是网格右列被滚动条吃掉一截。这里手工
    // 留 14px buffer（≈ scrollbar 宽 + 一点呼吸感），再算单元格尺寸。
    let total_w = (ui.available_width() - 14.0).max(0.0);
    let gap = 6.0_f32;
    let cell = ((total_w - gap * (cols as f32 - 1.0)) / cols as f32).floor();

    // 找到当前播放集的 key，用于高亮 + 默认展开。
    let active_key = movie
        .resources
        .iter()
        .find(|r| Some(r.id.as_str()) == active_id)
        .and_then(|r| match r.episode.as_deref() {
            None | Some("") => Some(EpKey::Movie),
            Some(s) => Some(match s.parse::<i32>() {
                Ok(n) => EpKey::Number(n),
                Err(_) => EpKey::Label(s.to_string()),
            }),
        });

    let entries: Vec<(EpKey, &Vec<&crate::native_player::meta::ResourceMeta>)> =
        groups.iter().map(|(k, v)| (k.clone(), v)).collect();

    for chunk in entries.chunks(cols) {
        ui.horizontal(|ui| {
            for (k, sources) in chunk {
                let label = match k {
                    EpKey::Number(n) => format!("{n}"),
                    EpKey::Label(s) => s.clone(),
                    EpKey::Movie => "正片".to_string(),
                };
                let is_active = active_key.as_ref() == Some(k);
                let (fill, border, text_color) = if is_active {
                    (
                        cyan.gamma_multiply(0.22),
                        cyan,
                        cyan,
                    )
                } else {
                    (
                        Color32::from_rgba_unmultiplied(255, 255, 255, 12),
                        Color32::from_rgba_unmultiplied(255, 255, 255, 28),
                        Color32::from_gray(220),
                    )
                };
                let resp = egui::Frame::default()
                    .fill(fill)
                    .stroke(egui::Stroke::new(1.0, border))
                    .corner_radius(egui::CornerRadius::same(6))
                    .show(ui, |ui| {
                        ui.set_width(cell);
                        ui.set_height(cell * 0.7);
                        ui.vertical_centered(|ui| {
                            ui.add_space((cell * 0.7 - 18.0) * 0.5);
                            ui.label(
                                egui::RichText::new(label)
                                    .color(text_color)
                                    .size(13.0)
                                    .strong()
                                    .monospace(),
                            );
                        });
                    });
                let interact = ui.interact(
                    resp.response.rect,
                    ui.id().with(("ep", &sources[0].id)),
                    egui::Sense::click(),
                );
                if interact.clicked() && !is_active && !sources[0].url.is_empty() {
                    actions.push(Action::SwitchResource {
                        id: sources[0].id.clone(),
                        url: sources[0].url.clone(),
                    });
                }
            }
        });
        ui.add_space(gap);
    }

    // 当前集下面展开多源切换（仅当该集 sources > 1）
    if let (Some(k), Some(_id)) = (active_key.as_ref(), active_id) {
        if let Some(sources) = groups.get(k) {
            if sources.len() > 1 {
                ui.add_space(10.0);
                ui.label(
                    egui::RichText::new("当前集 · 多源")
                        .color(Color32::from_gray(160))
                        .size(11.0),
                );
                ui.add_space(6.0);
                for src in sources {
                    draw_source_row(
                        ui,
                        src,
                        active_id == Some(src.id.as_str()),
                        actions,
                        cyan,
                    );
                    ui.add_space(6.0);
                }
            }
        }
    }
}

/// 一条「源」行：标题 + badge 链 + 大小，整行可点切源。
fn draw_source_row(
    ui: &mut egui::Ui,
    res: &crate::native_player::meta::ResourceMeta,
    is_active: bool,
    actions: &mut Vec<Action>,
    cyan: Color32,
) {
    // ScrollArea 给子 ui 的 max_rect 在水平方向不一定收紧，导致 Frame
    // 按子内容自然延展——长 badge / 长文件名 一旦突破 panel 边界，整张
    // 卡片就跟着延伸到 panel 之外。在画 frame 之前 set_max_width 把外层
    // ui 收回到 panel 实际可用宽度，frame 自己就会跟着缩。
    ui.set_max_width(ui.available_width());

    let (fill, stroke) = if is_active {
        (
            cyan.gamma_multiply(0.16),
            egui::Stroke::new(1.0, cyan.gamma_multiply(0.8)),
        )
    } else {
        (
            Color32::from_rgba_unmultiplied(255, 255, 255, 10),
            egui::Stroke::new(
                1.0,
                Color32::from_rgba_unmultiplied(255, 255, 255, 22),
            ),
        )
    };
    // 关键：先把当前 ui 的可用宽度 snapshot 下来。后面 frame inner_margin
    // 会减去左右各 10px，这就是卡片内部真正能放内容的宽度。把这个数字
    // **显式**算出来后用 allocate_ui_with_layout 创建一个固定宽度的 ui，
    // 强制 horizontal_wrapped / Label::wrap 拿到正确的折行边界。
    // egui 0.32 的 set_max_width / set_width 在 ScrollArea 内常因 inf
    // max_rect 失效——只有 allocate_ui_with_layout 这条路 100% 可靠。
    let panel_w = ui.available_width();
    let card_inner_w = (panel_w - 20.0 - 4.0).max(40.0); // 减去左右 inner_margin + 边框

    let resp = egui::Frame::default()
        .fill(fill)
        .stroke(stroke)
        .corner_radius(egui::CornerRadius::same(6))
        .inner_margin(egui::Margin::same(10))
        .show(ui, |ui| {
            ui.allocate_ui_with_layout(
                egui::vec2(card_inner_w, 0.0),
                egui::Layout::top_down(egui::Align::Min),
                |ui| {
                    ui.set_min_width(card_inner_w);
                    ui.set_max_width(card_inner_w);
            // display_label / filename / quality_label / 兜底"未命名源"。
            // 后端有时把 display_label/filename 给成空字符串（电影一类只有
            // 一个文件、没有片源元数据时），不能让 UI 直接渲染一张空卡片。
            let title_text = res
                .display_label
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    let f = res.filename.as_str();
                    if f.is_empty() { None } else { Some(f) }
                })
                .or_else(|| res.quality_label.as_deref().filter(|s| !s.is_empty()))
                .unwrap_or("未命名源");
            let title_color = if is_active { cyan } else { Color32::from_gray(225) };

            // 第一行：● 图标 + 存储源 chip。标题放第二行才能可靠折行。
            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new(if is_active { "▶" } else { "·" })
                        .color(if is_active { cyan } else { Color32::from_gray(120) })
                        .size(11.0),
                );
                if let Some(src_name) = res
                    .storage_source
                    .as_deref()
                    .filter(|s| !s.is_empty())
                {
                    egui::Frame::default()
                        .fill(cyan.gamma_multiply(0.9))
                        .corner_radius(egui::CornerRadius::same(3))
                        .inner_margin(egui::Margin {
                            left: 5,
                            right: 5,
                            top: 1,
                            bottom: 1,
                        })
                        .show(ui, |ui| {
                            ui.label(
                                egui::RichText::new(src_name.to_uppercase())
                                    .color(Color32::BLACK)
                                    .size(9.0)
                                    .strong()
                                    .monospace(),
                            );
                        });
                }
            });
            // 第二行：文件名标题，开 wrap，让超长名字按 panel 宽度折行。
            ui.add(
                egui::Label::new(
                    egui::RichText::new(title_text)
                        .color(title_color)
                        .size(12.0)
                        .strong(),
                )
                .wrap(),
            );

            if !res.badges.is_empty() {
                ui.add_space(4.0);
                // 不再依赖 egui 的 horizontal_wrapped / Layout main_wrap：在
                // ScrollArea + 嵌套 frame 的多重 max_rect 不收紧的情况下，
                // 那两条路径在 0.32 上都会失败（实测三轮全部漏 wrap）。
                // 改成手工测量 + 手动换行：遍历每个 badge，先把它的精确文本
                // 宽度算出来，加上 padding、stroke、间距后看本行剩余宽度
                // 是否够；不够就 ui.end_row()-style 起一行新 horizontal。
                draw_badges_manual_wrap(ui, &res.badges, card_inner_w);
            }
            if let Some(sz) = res.size_bytes {
                ui.add_space(2.0);
                let gb = sz as f64 / 1024.0 / 1024.0 / 1024.0;
                ui.with_layout(
                    egui::Layout::right_to_left(egui::Align::Center),
                    |ui| {
                        ui.label(
                            egui::RichText::new(format!("{:.2} GB", gb))
                                .color(Color32::from_gray(140))
                                .size(10.0)
                                .monospace(),
                        );
                    },
                );
            }
                },
            );
        });

    let interact = ui.interact(
        resp.response.rect,
        ui.id().with(("src", &res.id)),
        egui::Sense::click(),
    );
    if interact.clicked() && !is_active && !res.url.is_empty() {
        actions.push(Action::SwitchResource {
            id: res.id.clone(),
            url: res.url.clone(),
        });
    }
}

/// 手工把一组 badge 按指定最大宽度自动换行渲染。
///
/// 为什么不用 `ui.horizontal_wrapped` / `Layout::with_main_wrap`：在 egui
/// 0.32，ScrollArea + Frame 嵌套时子 ui 的 max_rect 在水平方向是 +∞
/// （ScrollArea 内部用滚动条延展尺寸），无论怎么 set_max_width / 套
/// allocate_ui_with_layout 都没法让 wrap 路径取到正确的右边界。结果就是
/// 长 badge（比如 "Blu-ray REMUX"）越过 panel 边沿被切。
///
/// 这里直接绕开：先按字体精确测量每个 badge 的 pixel 宽度（含内边距 +
/// 边框），手工累加 row_used；超过 max_w 就开一个新 horizontal 行。这样
/// max_rect 是什么并不重要——我们用算出来的 max_w 自己决定换行点。
fn draw_badges_manual_wrap(ui: &mut egui::Ui, badges: &[String], max_w: f32) {
    if badges.is_empty() {
        return;
    }
    // 与 draw_badge 内 inner_margin (5+5) + stroke (1+1) 对齐，再加 6px
    // 行内 spacing buffer，让相邻 badge 之间有呼吸空间。
    const PADDING: f32 = 5.0 + 5.0 + 1.0 + 1.0;
    const SPACING: f32 = 6.0;
    let font_id = egui::FontId::monospace(9.5);

    let mut rows: Vec<Vec<&str>> = vec![Vec::new()];
    let mut row_used = 0.0_f32;

    ui.fonts(|fonts| {
        for b in badges {
            let txt_w = fonts.layout_no_wrap(b.clone(), font_id.clone(), Color32::WHITE).rect.width();
            let need = txt_w + PADDING + if rows.last().unwrap().is_empty() { 0.0 } else { SPACING };
            if !rows.last().unwrap().is_empty() && row_used + need > max_w {
                rows.push(Vec::new());
                row_used = 0.0;
            }
            rows.last_mut().unwrap().push(b.as_str());
            row_used += if rows.last().unwrap().len() == 1 {
                txt_w + PADDING
            } else {
                need
            };
        }
    });

    for (i, row) in rows.iter().enumerate() {
        if i > 0 {
            ui.add_space(4.0);
        }
        ui.horizontal(|ui| {
            for b in row {
                draw_badge(ui, b);
            }
        });
    }
}

/// 画一个 badge — 颜色按内容分类（参考 web Player.tsx 1944~1965 行）：
///   - 4K / 1080p / 720p：青色
///   - HDR / Dolby Vision：黄色
///   - HEVC / H.265：青色弱
///   - Atmos / Dolby：紫色
///   - Bluray / WEB-DL / REMUX：蓝色弱
///   - 其他：灰色
fn draw_badge(ui: &mut egui::Ui, raw: &str) {
    let upper = raw.to_uppercase();
    let cyan = Color32::from_rgb(0x22, 0xd3, 0xee);
    let yellow = Color32::from_rgb(245, 240, 11);
    let purple = Color32::from_rgb(199, 34, 238);
    let (text, bg, border) = if upper.contains("4K")
        || upper.contains("1080P")
        || upper.contains("720P")
        || upper.contains("2160P")
    {
        (
            cyan,
            cyan.gamma_multiply(0.12),
            egui::Stroke::new(1.0, cyan.gamma_multiply(0.45)),
        )
    } else if upper.contains("HDR") || upper.contains("VISION") || upper.contains("DV") {
        (
            yellow,
            yellow.gamma_multiply(0.10),
            egui::Stroke::new(1.0, yellow.gamma_multiply(0.4)),
        )
    } else if upper.contains("ATMOS") || upper.contains("DOLBY") {
        (
            purple,
            purple.gamma_multiply(0.10),
            egui::Stroke::new(1.0, purple.gamma_multiply(0.4)),
        )
    } else if upper.contains("BLU-RAY")
        || upper.contains("BLURAY")
        || upper.contains("WEB-DL")
        || upper.contains("WEBDL")
        || upper.contains("REMUX")
    {
        let blue = Color32::from_rgb(0x60, 0xa5, 0xfa);
        (
            blue,
            blue.gamma_multiply(0.12),
            egui::Stroke::new(1.0, blue.gamma_multiply(0.4)),
        )
    } else {
        (
            Color32::from_gray(200),
            Color32::from_rgba_unmultiplied(255, 255, 255, 10),
            egui::Stroke::new(1.0, Color32::from_rgba_unmultiplied(255, 255, 255, 25)),
        )
    };
    egui::Frame::default()
        .fill(bg)
        .stroke(border)
        .corner_radius(egui::CornerRadius::same(3))
        .inner_margin(egui::Margin {
            left: 5,
            right: 5,
            top: 1,
            bottom: 1,
        })
        .show(ui, |ui| {
            // 单 badge 内部禁用 wrap：badge 文字（"Bluray Remux"）一旦
            // 换行就会一字一列竖向堆叠，跟用户期望的横排标签彻底背离。
            // egui 默认按 layout 剩余宽度 wrap，要靠 extend 强制单行。
            ui.add(
                egui::Label::new(
                    egui::RichText::new(raw)
                        .color(text)
                        .size(9.5)
                        .strong()
                        .monospace(),
                )
                .extend(),
            );
        });
}

/// 集数排序键。`Number` 走自然数序，`Label`（特别篇 / SP / OVA 等）走
/// 字典序，`Movie` 留给电影/单文件，永远在最前面。
#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
enum EpKey {
    Movie,
    Number(i32),
    Label(String),
}

fn format_time(seconds: f64) -> String {
    if !seconds.is_finite() || seconds < 0.0 {
        return "00:00".into();
    }
    let total = seconds as i64;
    let h = total / 3600;
    let m = (total % 3600) / 60;
    let s = total % 60;
    if h > 0 {
        format!("{h}:{m:02}:{s:02}")
    } else {
        format!("{m:02}:{s:02}")
    }
}

fn make_theme() -> egui::Visuals {
    let mut v = egui::Visuals::dark();
    let cyan = Color32::from_rgb(0x22, 0xd3, 0xee);
    v.override_text_color = Some(Color32::WHITE);
    v.hyperlink_color = cyan;
    v.selection.bg_fill = cyan.gamma_multiply(0.4);
    v.selection.stroke = Stroke::new(1.0, cyan);
    v.widgets.hovered.bg_fill = Color32::from_rgba_unmultiplied(255, 255, 255, 30);
    v.widgets.active.bg_fill = cyan.gamma_multiply(0.5);
    v.widgets.inactive.bg_fill = Color32::from_rgba_unmultiplied(255, 255, 255, 10);
    v.widgets.inactive.fg_stroke = Stroke::new(1.0, Color32::from_gray(220));
    v
}

/// Load a Windows system CJK font + symbol/emoji fallback fonts and put
/// them at the front of both font families so 中文 / 标点 / 全角字符 /
/// ▼ / ✕ / 🔊 等都能正确渲染。msyh 缺符号/emoji 字形，没有 fallback
/// 时会显示成 □（"豆腐块"），底栏控件按钮一片抽象。
///
/// Returns None if none of the CJK fonts are present (Win10/11 默认都装
/// 了，几乎不会触发；做兜底避免 panic）。symbol/emoji fallback 缺失
/// 时静默跳过——只会回退到 □，不影响其他文本。
fn load_cjk_fonts() -> Option<FontDefinitions> {
    const CJK_CANDIDATES: &[&str] = &[
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ];
    let cjk_bytes = CJK_CANDIDATES
        .iter()
        .find_map(|p| std::fs::read(p).ok())?;

    let mut fonts = FontDefinitions::default();

    // 主 CJK 字体放最前——汉字、中文标点优先它。
    fonts.font_data.insert(
        "cjk".into(),
        Arc::new(FontData::from_owned(cjk_bytes)),
    );

    // 准备 fallback 链：CJK 主体之后立刻放 media-icons —— 因为 Segoe Fluent
    // Icons 把媒体控件图标放在 Unicode Private Use Area (E000-F8FF)，必须排
    // 在 seguisym 之前命中。否则 seguisym 会"声明拥有"这些 PUA 码点但渲染
    // 出空 glyph，结果按钮一片空白。
    let mut order: Vec<String> = vec!["cjk".into()];

    // Material-style 媒体图标 fallback：Segoe Fluent Icons (Win11) 或 Segoe
    // MDL2 Assets (Win10)。SegoeIcons.ttf 是 Win11 新名（覆盖更全）；
    // segmdl2.ttf 是老 Win10 名，作为兜底。
    let icon_candidates: &[&str] = &[
        r"C:\Windows\Fonts\SegoeIcons.ttf",
        r"C:\Windows\Fonts\segmdl2.ttf",
    ];
    if let Some(icon_bytes) = icon_candidates
        .iter()
        .find_map(|p| std::fs::read(p).ok())
    {
        fonts
            .font_data
            .insert("media-icons".into(), Arc::new(FontData::from_owned(icon_bytes)));
        order.push("media-icons".into());
    }

    // Symbol fallback：seguisym.ttf 含 ▼ ▴ ✕ ✓ 等几何符号；放在 media-icons
    // 之后，让 CJK / PUA 之外的符号能命中。
    if let Ok(sym) = std::fs::read(r"C:\Windows\Fonts\seguisym.ttf") {
        fonts
            .font_data
            .insert("sys-symbol".into(), Arc::new(FontData::from_owned(sym)));
        order.push("sys-symbol".into());
    }
    // Emoji fallback：seguiemj.ttf 含 🔊 等 emoji。egui 自身的 emoji-icon-font
    // 已经覆盖一部分，但 seguiemj 更全。失败也无所谓。
    if let Ok(emj) = std::fs::read(r"C:\Windows\Fonts\seguiemj.ttf") {
        fonts
            .font_data
            .insert("sys-emoji".into(), Arc::new(FontData::from_owned(emj)));
        order.push("sys-emoji".into());
    }

    let proportional = fonts.families.entry(FontFamily::Proportional).or_default();
    for (i, name) in order.iter().enumerate() {
        proportional.insert(i, name.clone());
    }
    let mono = fonts.families.entry(FontFamily::Monospace).or_default();
    for (i, name) in order.iter().enumerate() {
        mono.insert(i, name.clone());
    }

    Some(fonts)
}
