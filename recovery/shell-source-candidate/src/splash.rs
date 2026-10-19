// CyberStream PC · 启动 splash 窗口
//
// 目的：把"双击图标 → webview 加载 React bundle → sidecar 起来 → 数据填充"
// 这段 3-6 秒的空白期用一个独立小窗口盖住，不让用户看见黑屏 / 半透明白屏。
//
// 设计：
//   - splash 是独立的 WebviewWindow，无边框 + 透明 + always_on_top + 居中
//   - 它在 setup() 第一时间创建，比主窗口更早出现（主窗口 visible:false 默认）
//   - HTML/CSS 内嵌（include_str!），不依赖前端 dist，所以加载只要几十毫秒
//   - sidecar 健康探针 + 主窗口 React mount 完成后，前端 invoke `splash_done`
//     → Rust 同时 emit 淡出事件给 splash + show 主窗 + 关 splash
//
// 为什么不直接用 tauri.conf.json 声明 splash 窗口：
//   - 主窗口 visible:false 已经在 conf 里了
//   - splash 要走 include_str! 的内嵌 HTML、走 data: URL 加载，conf 里
//     不好声明。在 Rust 侧动态建窗口最简单
//
// 备注：splash 创建失败不致命 —— 退化成"主窗口 visible:false 直到 ready"，
// 用户看到的是任务栏图标但桌面上空空的 1-2 秒，比黑窗口好不到哪里去但也
// 不会崩。所以 create_splash 返回 Result 但调用方 ignore err。

use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

const SPLASH_LABEL: &str = "splash";
const SPLASH_HTML: &str = include_str!("../splash.html");

/// 创建并展示 splash 窗口。在 setup() 最开始调，比 sidecar spawn 还要早。
pub fn create_splash(app: &AppHandle) -> Result<(), String> {
    // data: URL 把整个 HTML 内嵌进去，无需 frontend dist 路径解析
    let data_url = format!(
        "data:text/html;charset=utf-8;base64,{}",
        base64_encode(SPLASH_HTML)
    );
    let url = data_url
        .parse::<tauri::Url>()
        .map_err(|e| format!("splash data url parse: {e}"))?;

    WebviewWindowBuilder::new(app, SPLASH_LABEL, WebviewUrl::External(url))
        .title("CyberStream")
        .inner_size(480.0, 360.0)
        .resizable(false)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(false) // 留 taskbar 图标，让用户能确认应用确实启动了
        .center()
        .visible(true)
        .build()
        .map_err(|e| format!("splash build: {e}"))?;

    Ok(())
}

/// 推送阶段文案到 splash（"等待后端..." / "准备就绪" 这类）。
/// splash 已关闭时是 no-op。
pub fn set_phase(app: &AppHandle, text: &str) {
    if let Some(win) = app.get_webview_window(SPLASH_LABEL) {
        let _ = win.emit("splash:phase", text);
    }
}

/// 淡出 splash + 显示主窗口。前端 invoke `splash_done` 时调到这里。
pub fn finish(app: &AppHandle) {
    // 先让 splash 走 fade-out 动画 (240ms)
    if let Some(splash) = app.get_webview_window(SPLASH_LABEL) {
        let _ = splash.emit("splash:fade-out", ());
        let app_clone = app.clone();
        // 给动画一点时间，再关 splash
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(280));
            if let Some(splash) = app_clone.get_webview_window(SPLASH_LABEL) {
                let _ = splash.close();
            }
        });
    }
    // 主窗口立刻显示 + focus
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }
}

/// `#[tauri::command]` 暴露给前端：sidecar ready + React 完成 mount 后调用
#[tauri::command]
pub fn splash_done(app: AppHandle) {
    finish(&app);
}

// ── 内置 base64 编码 ────────────────────────────────────────────────────────
// 不引入新 crate，splash.html 几 KB 用纯 std 编 base64 完全没问题
fn base64_encode(input: &str) -> String {
    const TBL: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b0 = chunk[0];
        let b1 = chunk.get(1).copied().unwrap_or(0);
        let b2 = chunk.get(2).copied().unwrap_or(0);
        out.push(TBL[(b0 >> 2) as usize] as char);
        out.push(TBL[(((b0 & 0x03) << 4) | (b1 >> 4)) as usize] as char);
        if chunk.len() >= 2 {
            out.push(TBL[(((b1 & 0x0f) << 2) | (b2 >> 6)) as usize] as char);
        } else {
            out.push('=');
        }
        if chunk.len() >= 3 {
            out.push(TBL[(b2 & 0x3f) as usize] as char);
        } else {
            out.push('=');
        }
    }
    out
}
