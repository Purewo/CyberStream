// CyberStream PC · 后端 sidecar 管理
//
// 作用：单机分发场景下，桌面客户端需要把 Flask 后端 (cyber-backend.exe)
// 当 sidecar 子进程拉起来。后端冻结模式默认 127.0.0.1:49152。
//
// 设计：
//   - 启动顺序：先 spawn → 起一个后台线程读 stdout 喂日志 → 主线程
//     轮询 GET /  探活，最多等 30 秒，OK 后回到 Tauri 启动流程；
//   - 退出：Tauri RunEvent::Exit 时 kill 子进程，避免桌面 APP 关了
//     但 49152 端口还被占着；
//   - 状态：用 std::sync::Mutex<Option<CommandChild>> 持有句柄，让
//     退出回调能拿到。
//
// 不在这里做的事：
//   - 端口冲突自动让步：用户已确认 fail-fast，被占就直接报错；
//   - 安装时迁移：DB 在 LOCALAPPDATA 下、首次启动后端会自动 ensure
//     schema，不需要前置脚本。

use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// 后端探活目标。冻结模式下 backend/run.py 把 host 锁成 127.0.0.1，端口
/// 49152；这两个值要跟 backend/config.py 里 IS_FROZEN 分支保持一致，
/// 同步改时记得两边都动。
const HEALTH_URL: &str = "http://127.0.0.1:49152/";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const PROBE_INTERVAL: Duration = Duration::from_millis(250);

pub struct BackendState {
    child: Mutex<Option<CommandChild>>,
}

impl BackendState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    /// kill child if any. Idempotent —— Tauri 退出回调和 panic
    /// fallback 都可能调它。
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.take() {
                if let Err(e) = child.kill() {
                    log::warn!("[backend] kill sidecar failed: {e}");
                } else {
                    log::info!("[backend] sidecar killed");
                }
            }
        }
    }

    fn store(&self, child: CommandChild) {
        if let Ok(mut guard) = self.child.lock() {
            *guard = Some(child);
        }
    }
}

/// 启动后端 sidecar，阻塞到健康检查 200 或超时；超时返回 Err 让上层决定
/// 是直接 panic 还是降级。
///
/// **必须在 Tauri AppHandle setup 之后调用** —— ShellExt 依赖 plugin 已
/// init；lib.rs 里我们在 .setup() 闭包里调它。
///
/// 调试逃生口：设环境变量 `CYBER_SKIP_BACKEND_SIDECAR=1` 时跳过 spawn，
/// 直接进入探活循环。这样调试时可以在外面的终端单独跑 backend（dev or
/// frozen exe），看完整 stdout/stderr，Tauri 壳跟那个外部后端连上即可。
pub fn spawn_and_wait_ready(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<BackendState>();

    let skip_spawn = std::env::var("CYBER_SKIP_BACKEND_SIDECAR")
        .map(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes"))
        .unwrap_or(false);

    if skip_spawn {
        log::info!("[backend] CYBER_SKIP_BACKEND_SIDECAR set, skipping spawn; expecting backend on {HEALTH_URL}");
    } else {
        // tauri-plugin-shell 的 sidecar API 按 tauri.conf.json 里 externalBin
        // 注册过的"二进制名"找文件。我们填的 "binaries/cyber-backend"，所以
        // sidecar("cyber-backend") 就能解析到 binaries/cyber-backend-<triple>.exe。
        let cmd = app
            .shell()
            .sidecar("cyber-backend")
            .map_err(|e| format!("sidecar lookup failed: {e}"))?;

        let (mut rx, child) = cmd
            .spawn()
            .map_err(|e| format!("sidecar spawn failed: {e}"))?;
        log::info!("[backend] sidecar spawned, pid={}", child.pid());
        state.store(child);

        // 后台线程吸 stdout / stderr / exit code 喂到 log。不读会让 OS pipe
        // buffer 满后导致后端 print 阻塞。
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        log::info!("[backend stdout] {}", String::from_utf8_lossy(&line));
                    }
                    CommandEvent::Stderr(line) => {
                        log::warn!("[backend stderr] {}", String::from_utf8_lossy(&line));
                    }
                    CommandEvent::Error(err) => {
                        log::error!("[backend] runtime error: {err}");
                    }
                    CommandEvent::Terminated(payload) => {
                        log::warn!(
                            "[backend] sidecar terminated code={:?} signal={:?}",
                            payload.code,
                            payload.signal
                        );
                        break;
                    }
                    _ => {}
                }
            }
        });
    }

    // 探活：blocking 调 reqwest 走 rustls，桌面端没装 OpenSSL 也能跑。
    let started = Instant::now();
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("probe client build failed: {e}"))?;

    while started.elapsed() < STARTUP_TIMEOUT {
        match client.get(HEALTH_URL).send() {
            Ok(resp) if resp.status().is_success() => {
                log::info!(
                    "[backend] ready in {:?}, status={}",
                    started.elapsed(),
                    resp.status()
                );
                return Ok(());
            }
            Ok(resp) => {
                log::debug!("[backend] probe non-2xx: {}", resp.status());
            }
            Err(_) => {
                // 后端还没起来，连接会被 refuse —— 这是预期，继续轮询。
            }
        }
        std::thread::sleep(PROBE_INTERVAL);
    }

    Err(format!(
        "backend did not become ready within {:?}",
        STARTUP_TIMEOUT
    ))
}

/// Tauri RunEvent::Exit 时调，杀掉 sidecar。
pub fn handle_run_event(app: &AppHandle, event: &RunEvent) {
    if matches!(event, RunEvent::Exit) {
        if let Some(state) = app.try_state::<BackendState>() {
            state.shutdown();
        }
    }
}
