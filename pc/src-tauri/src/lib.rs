// CyberStream PC · library entry
//
// v3 architecture: webview shell handles every page except the player.
// When the user picks "play", the webview invokes `open_pc_player` and
// the Rust side spins up a native Win32 window with libmpv + egui HUD
// (see `native_player/`). Everything from v0~v2.1 (mpv.exe + IPC, child
// HWND embedding) was removed in M3.4 because it's permanently dead
// code.

mod external_player;
mod native_player;
pub mod proxy;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // 启动顺序很关键：WebView2 在 builder 创建窗口时就会读取
    // WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS，所以代理必须在 Builder
    // 开始前就 set_var 进去；运行时再改对已开的 webview 完全无效。
    //
    // 永远显式指定 --proxy-server，无论用户有没有配应用代理：
    //   - 配了 → --proxy-server=<url>
    //   - 没配 → --proxy-server=direct://（Chromium 内置「强制直连」标记，
    //     连同局域网也不绕走系统代理）
    // 这样 v2rayN 等系统级代理工具开「自动代理」时也不会把客户端的请求
    // 拽走。注意：set_var 只影响当前进程，外部 IE/Edge/Chrome 的系统代理
    // 设置原封不动。
    let app_proxy = proxy::init_from_disk();
    let proxy_arg = match app_proxy.as_deref() {
        Some(url) if !url.is_empty() => format!("--proxy-server={url}"),
        _ => "--proxy-server=direct://".to_string(),
    };
    std::env::set_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", proxy_arg);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            ping,
            native_player::open_pc_player,
            external_player::launch_external_player,
            proxy::get_proxy_config,
            proxy::set_proxy_config,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Sanity check command invoked by the frontend platform adapter to verify the
/// PC runtime is wired up. Returns the static client version.
#[tauri::command]
fn ping() -> &'static str {
    env!("CARGO_PKG_VERSION")
}
