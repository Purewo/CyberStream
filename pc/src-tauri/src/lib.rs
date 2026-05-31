// CyberStream PC · library entry
//
// v3 architecture: webview shell handles every page except the player.
// When the user picks "play", the webview invokes `open_pc_player` and
// the Rust side spins up a native Win32 window with libmpv + egui HUD
// (see `native_player/`). Everything from v0~v2.1 (mpv.exe + IPC, child
// HWND embedding) was removed in M3.4 because it's permanently dead
// code.

mod backend;
mod external_player;
mod media_proxy;
mod native_player;
pub mod proxy;
mod splash;

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

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(backend::BackendState::new())
        .setup(|app| {
            // splash 第一时间出现 —— 比 sidecar spawn 还要早，让用户立刻看到
            // 「应用真的启动了」。失败也不致命：退化成主窗口 visible:false
            // 等 ready 自己冒出来。
            if let Err(e) = splash::create_splash(&app.handle()) {
                log::warn!("[splash] create failed (degrading to no-splash): {e}");
            } else {
                splash::set_phase(&app.handle(), "初始化界面 ...");
            }

            // 拉起捆绑的 cyber-backend.exe。spawn_and_wait_ready 内部探活搬到
            // 后台线程，setup 立刻返回；探活成功后会 emit `splash:phase` 切到
            // 「准备就绪」，前端 React mount 完成后 invoke splash_done 关 splash
            // 显主窗。
            if let Err(e) = backend::spawn_and_wait_ready(&app.handle()) {
                return Err(format!("backend bootstrap failed: {e}").into());
            }

            // 启动本地媒体代理（外部播放器 UA 改写用）。绑定 127.0.0.1
            // 随机端口；失败不致命，前端拿不到 base 时降级到原 URL（百度
            // 网盘外播会 403，其他云盘正常）。
            tauri::async_runtime::spawn(async move {
                let _ = media_proxy::start().await;
            });

            // 没有 sidecar 的 lite 构建直接告诉 splash 后端已就绪（前端连远程
            // 后端，splash 关闭由前端主导）。
            // —— 注：spawn_and_wait_ready 内部的健康探针成功时也会推 phase，
            // 这里不重复。
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ping,
            splash::splash_done,
            native_player::open_pc_player,
            external_player::launch_external_player,
            proxy::get_proxy_config,
            proxy::set_proxy_config,
            media_proxy::media_proxy_url,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        backend::handle_run_event(handle, &event);
    });
}

/// Sanity check command invoked by the frontend platform adapter to verify the
/// PC runtime is wired up. Returns the static client version.
#[tauri::command]
fn ping() -> &'static str {
    env!("CARGO_PKG_VERSION")
}
