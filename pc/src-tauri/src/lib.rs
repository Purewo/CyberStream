// CyberStream PC · library entry
//
// M0 scope: just enough to bring up an empty Tauri window that loads the
// existing React frontend. mpv embedding lands in M3 (mpv.rs).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![ping])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Sanity check command invoked by the frontend platform adapter to verify the
/// PC runtime is wired up. Returns the static client version.
#[tauri::command]
fn ping() -> &'static str {
    env!("CARGO_PKG_VERSION")
}
