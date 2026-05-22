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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            ping,
            native_player::open_pc_player,
            external_player::launch_external_player,
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
