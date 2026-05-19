// CyberStream PC · libmpv embedding via JSON-IPC.
//
// Rather than linking libmpv directly (libmpv-sys), we spawn the bundled
// mpv.exe as a child process and talk to it over a named pipe. Pros:
// - simpler Rust glue, easier crash recovery, identical protocol on every
//   Windows host;
// - playback latency overhead is sub-millisecond — mpv's render thread is
//   independent of IPC.
// Cons:
// - mpv runs in its own window, so we have to ask Tauri's HWND APIs to
//   parent it under the main webview. That parenting lives in window.rs.
//
// Threading model: each session owns one writer half of the pipe (kept on
// the Tokio task) and a reader task that fans events into the AppHandle.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, Runtime, State};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::windows::named_pipe::{ClientOptions, NamedPipeClient};
use tokio::process::{Child, Command};
use tokio::sync::{oneshot, Mutex};
use tokio::time::{sleep, Duration};

#[derive(Default)]
pub struct MpvManager {
    inner: Arc<Mutex<Option<Session>>>,
    next_request_id: AtomicU64,
}

struct Session {
    process: Child,
    /// Pipe writer half. Reads happen on a background task that emits Tauri
    /// events; we never poll responses synchronously here — instead we route
    /// them through `pending` keyed on request_id.
    writer: tokio::io::WriteHalf<NamedPipeClient>,
    pending: Arc<Mutex<HashMap<u64, oneshot::Sender<MpvIpcMessage>>>>,
    #[allow(dead_code)] // kept for diagnostics; surfaced to the frontend in mpv_start's return
    pipe_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
enum MpvIpcMessage {
    Response {
        request_id: u64,
        error: String,
        #[serde(default)]
        data: Value,
    },
    Event {
        event: String,
        #[serde(default, flatten)]
        rest: Value,
    },
}

impl MpvManager {
    pub fn new() -> Self {
        Self::default()
    }

    /// Start (or restart) the mpv subprocess. If `parent_hwnd` is provided,
    /// mpv embeds its render surface as a child of that window via the
    /// `--wid` option — the standard way to put libmpv inside a host app.
    /// Returns the pipe name so the frontend can correlate diagnostics.
    pub async fn start<R: Runtime>(
        &self,
        app: AppHandle<R>,
        mpv_exe: PathBuf,
        parent_hwnd: Option<isize>,
    ) -> Result<String, String> {
        let mut guard = self.inner.lock().await;
        if guard.is_some() {
            // Already running — caller should call stop() first.
            return Err("mpv session already running".into());
        }

        let pipe_name = format!(
            "\\\\.\\pipe\\cyberstream-mpv-{}-{}",
            std::process::id(),
            chrono_like_seconds()
        );

        let mut cmd = Command::new(&mpv_exe);
        cmd.args([
            "--idle=yes",
            "--no-config",
            "--no-terminal",
            "--no-input-default-bindings",
            "--keep-open=yes",
            "--force-window=yes",
            "--ontop=no",
            // Hardware decoding: auto picks the best available
            // (d3d11va > nvdec > dxva2). User can still override per-file.
            "--hwdec=auto-safe",
            "--vo=gpu-next",
            &format!("--input-ipc-server={}", pipe_name),
        ]);

        if let Some(hwnd) = parent_hwnd {
            cmd.arg(format!("--wid={hwnd}"));
        }

        let mut child = cmd
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("failed to spawn mpv: {e}"))?;

        // Connect to the pipe (mpv may take a moment to create it).
        let pipe = connect_pipe_with_retry(&pipe_name, 30, Duration::from_millis(150))
            .await
            .map_err(|e| {
                let _ = child.start_kill();
                format!("could not open mpv IPC pipe {pipe_name}: {e}")
            })?;

        let (read_half, write_half) = tokio::io::split(pipe);
        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<MpvIpcMessage>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        // Reader task: parse one JSON message per line, dispatch to pending
        // request handlers or emit a Tauri event for everything else.
        let pending_for_reader = Arc::clone(&pending);
        let app_for_reader = app.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(read_half);
            let mut line = String::new();
            loop {
                line.clear();
                match reader.read_line(&mut line).await {
                    Ok(0) => break, // EOF — mpv exited
                    Ok(_) => {
                        let trimmed = line.trim();
                        if trimmed.is_empty() {
                            continue;
                        }
                        // Try response first.
                        if let Ok(msg) = serde_json::from_str::<Value>(trimmed) {
                            if let Some(rid) = msg.get("request_id").and_then(|v| v.as_u64()) {
                                let mut p = pending_for_reader.lock().await;
                                if let Some(tx) = p.remove(&rid) {
                                    let _ = tx.send(MpvIpcMessage::Response {
                                        request_id: rid,
                                        error: msg
                                            .get("error")
                                            .and_then(|v| v.as_str())
                                            .unwrap_or("")
                                            .to_string(),
                                        data: msg.get("data").cloned().unwrap_or(Value::Null),
                                    });
                                }
                                continue;
                            }
                            if let Some(event) = msg.get("event").and_then(|v| v.as_str()) {
                                let _ = app_for_reader.emit(
                                    "mpv:event",
                                    json!({
                                        "event": event,
                                        "data": msg,
                                    }),
                                );
                            }
                        }
                    }
                    Err(_) => break,
                }
            }
            // Notify frontend that the session ended unexpectedly.
            let _ = app_for_reader.emit("mpv:exit", json!({}));
        });

        *guard = Some(Session {
            process: child,
            writer: write_half,
            pending,
            pipe_name: pipe_name.clone(),
        });

        Ok(pipe_name)
    }

    pub async fn stop(&self) -> Result<(), String> {
        let mut guard = self.inner.lock().await;
        if let Some(mut session) = guard.take() {
            // Best-effort graceful quit.
            let _ = session
                .writer
                .write_all(b"{\"command\":[\"quit\"]}\n")
                .await;
            // Force-kill if it dawdles.
            let _ = session.process.start_kill();
            let _ = session.process.wait().await;
        }
        Ok(())
    }

    /// Issue a JSON-IPC command and await the reply.
    pub async fn command(&self, args: Value) -> Result<Value, String> {
        let request_id = self.next_request_id.fetch_add(1, Ordering::Relaxed) + 1;
        let payload = json!({
            "command": args,
            "request_id": request_id,
        });
        let line = serde_json::to_string(&payload).map_err(|e| e.to_string())? + "\n";

        let (tx, rx) = oneshot::channel();

        let pending = {
            let guard = self.inner.lock().await;
            let session = guard
                .as_ref()
                .ok_or_else(|| "mpv session not started".to_string())?;
            session.pending.clone()
        };
        pending.lock().await.insert(request_id, tx);

        {
            let mut guard = self.inner.lock().await;
            let session = guard
                .as_mut()
                .ok_or_else(|| "mpv session not started".to_string())?;
            session
                .writer
                .write_all(line.as_bytes())
                .await
                .map_err(|e| format!("ipc write: {e}"))?;
        }

        match tokio::time::timeout(Duration::from_secs(5), rx).await {
            Ok(Ok(MpvIpcMessage::Response { error, data, .. })) => {
                if error == "success" {
                    Ok(data)
                } else {
                    Err(format!("mpv: {error}"))
                }
            }
            Ok(Ok(_)) => Err("unexpected ipc message".into()),
            Ok(Err(_)) => Err("mpv ipc channel dropped".into()),
            Err(_) => {
                pending.lock().await.remove(&request_id);
                Err("mpv ipc timeout".into())
            }
        }
    }
}

async fn connect_pipe_with_retry(
    pipe: &str,
    attempts: usize,
    delay: Duration,
) -> Result<NamedPipeClient, String> {
    for _ in 0..attempts {
        match ClientOptions::new().open(pipe) {
            Ok(client) => return Ok(client),
            Err(e) if matches!(e.kind(), std::io::ErrorKind::NotFound) => {
                sleep(delay).await;
            }
            Err(e) => return Err(e.to_string()),
        }
    }
    Err(format!("pipe {pipe} never appeared"))
}

fn chrono_like_seconds() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

// ---------- Tauri commands ---------------------------------------------------

fn resolve_mpv_exe<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    // Bundle layout: tauri-bundler stores `../vendor/mpv/*` resources under
    // resource_dir()/_up_/vendor/mpv/* on Windows. Older Tauri versions used
    // a flat layout, so we probe a couple of candidates before giving up.
    if let Ok(rd) = app.path().resource_dir() {
        let candidates = [
            rd.join("_up_").join("vendor").join("mpv").join("mpv.exe"),
            rd.join("vendor").join("mpv").join("mpv.exe"),
            rd.join("mpv").join("mpv.exe"),
            rd.join("mpv.exe"),
        ];
        for p in &candidates {
            if p.exists() {
                return Ok(p.clone());
            }
        }
    }
    // Dev fallback: pc/vendor/mpv/mpv.exe relative to pc/src-tauri/.
    if let Ok(cwd) = std::env::current_dir() {
        let dev = cwd.join("..").join("vendor").join("mpv").join("mpv.exe");
        if dev.exists() {
            return Ok(dev);
        }
    }
    Err("mpv.exe not found (looked in resource_dir candidates and ../vendor/mpv)".into())
}

#[tauri::command]
pub async fn mpv_start<R: Runtime>(
    app: AppHandle<R>,
    state: State<'_, MpvManager>,
    parent_hwnd: Option<isize>,
) -> Result<String, String> {
    let exe = resolve_mpv_exe(&app)?;
    // Resolve the main window's HWND when the frontend asked for embedding
    // but didn't pass an explicit HWND. Tauri's window handle returns a
    // platform-typed value; on Windows we re-cast it to isize for the CLI.
    let resolved_hwnd: Option<isize> = match parent_hwnd {
        Some(h) => Some(h),
        None => {
            #[cfg(target_os = "windows")]
            {
                app.get_webview_window("main")
                    .and_then(|w| w.hwnd().ok())
                    .map(|h| h.0 as isize)
            }
            #[cfg(not(target_os = "windows"))]
            {
                None
            }
        }
    };
    state.start(app.clone(), exe, resolved_hwnd).await
}

#[tauri::command]
pub async fn mpv_stop(state: State<'_, MpvManager>) -> Result<(), String> {
    state.stop().await
}

#[tauri::command]
pub async fn mpv_command(
    state: State<'_, MpvManager>,
    args: Value,
) -> Result<Value, String> {
    state.command(args).await
}

#[tauri::command]
pub async fn mpv_load_file(
    state: State<'_, MpvManager>,
    url: String,
    headers: Option<Vec<String>>,
    start: Option<f64>,
) -> Result<Value, String> {
    // Inject HTTP auth headers (e.g. "Authorization: Bearer xxx") via mpv's
    // --http-header-fields option, set per-file before the loadfile call.
    if let Some(hdrs) = headers {
        if !hdrs.is_empty() {
            state
                .command(json!(["set_property", "http-header-fields", hdrs]))
                .await?;
        }
    }
    if let Some(t) = start {
        let _ = state
            .command(json!(["set_property", "start", format!("{t}")]))
            .await;
    }
    state
        .command(json!(["loadfile", url, "replace"]))
        .await
}

#[tauri::command]
pub async fn mpv_set_property(
    state: State<'_, MpvManager>,
    name: String,
    value: Value,
) -> Result<Value, String> {
    state.command(json!(["set_property", name, value])).await
}

#[tauri::command]
pub async fn mpv_get_property(
    state: State<'_, MpvManager>,
    name: String,
) -> Result<Value, String> {
    state.command(json!(["get_property", name])).await
}

#[tauri::command]
pub async fn mpv_observe_property(
    state: State<'_, MpvManager>,
    name: String,
    id: u64,
) -> Result<Value, String> {
    state.command(json!(["observe_property", id, name])).await
}
