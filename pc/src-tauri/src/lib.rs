// CyberStream PC · library entry
//
// Wires the Tauri shell, plugins, and the mpv embedding bridge.

mod mpv;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(mpv::MpvManager::new())
        .invoke_handler(tauri::generate_handler![
            ping,
            mpv::mpv_start,
            mpv::mpv_stop,
            mpv::mpv_command,
            mpv::mpv_load_file,
            mpv::mpv_set_property,
            mpv::mpv_get_property,
            mpv::mpv_observe_property,
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
