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

/// 启动后端 sidecar 并立刻返回 —— 探活搬到后台线程，**不阻塞 setup()**。
///
/// 之前版本在主线程同步阻塞 30 秒等健康检查，会把 Tauri webview 创建推后，
/// `__TAURI_INTERNALS__` 注入也跟着滞后；现在 setup 立刻返回，探活在
/// 后台线程里慢慢跑，没就绪只 log 一行 warn，前端首请求会自然 5xx。
///
/// **必须在 Tauri AppHandle setup 之后调用** —— ShellExt 依赖 plugin 已
/// init；lib.rs 里我们在 .setup() 闭包里调它。
///
/// 三种运行形态都要支持：
/// 1. **全套版 MSI**：tauri.conf.json 声明了 externalBin，sidecar exe 跟
///    主程序一起装到 Program Files；spawn 后立刻返回，探活在后台。
/// 2. **纯前端版 MSI**：没有 sidecar exe（用户连自己的 NAS 后端）。
///    `app.shell().sidecar(...)` 或 spawn 返回 Err 时降级到 webview-only
///    模式，前端连用户在设置里配的远程后端。
/// 3. **dev 调试**：设 `CYBER_SKIP_BACKEND_SIDECAR=1` 跳过 spawn 直连
///    外部后端（手动起的 sidecar exe / waitress dev）。
pub fn spawn_and_wait_ready(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<BackendState>();

    let skip_spawn = std::env::var("CYBER_SKIP_BACKEND_SIDECAR")
        .map(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes"))
        .unwrap_or(false);

    if skip_spawn {
        log::info!("[backend] CYBER_SKIP_BACKEND_SIDECAR set, skipping spawn; expecting backend on {HEALTH_URL}");
        spawn_health_probe();
        return Ok(());
    }

    // tauri-plugin-shell 的 sidecar API 按 tauri.conf.json 里 externalBin
    // 注册过的"二进制名"找文件。我们填的 "binaries/cyber-backend"，所以
    // sidecar("cyber-backend") 就能解析到 binaries/cyber-backend-<triple>.exe。
    //
    // 纯前端版 MSI 没把 sidecar 打进去 —— sidecar() 会返回 Err。这种
    // 情况下不要 panic，直接 Ok 让 shell 继续；前端会连用户配置的远程
    // 后端（默认 127.0.0.1:49152，但用户能在设置里改）。
    let cmd = match app.shell().sidecar("cyber-backend") {
        Ok(cmd) => cmd,
        Err(e) => {
            log::info!(
                "[backend] sidecar not bundled (lite build), running webview-only mode: {e}"
            );
            return Ok(());
        }
    };

    let (mut rx, child) = match cmd.spawn() {
        Ok(pair) => pair,
        Err(e) => {
            // spawn 失败的两种典型场景：
            //   1. lite 构建残留：tauri 嵌入式 manifest 注册了 sidecar
            //      但 MSI 实际没打 exe。OS 报 "找不到指定的文件"。
            //   2. 缺 DLL / 杀软拦截 / 防火墙拦截。
            // 两种情况都不应该 panic 让窗口闪退；降级到 webview-only 模式，
            // 让用户在「设置 → 后端服务器」里改成自己的远程后端。
            log::warn!(
                "[backend] sidecar spawn failed, falling back to webview-only mode: {e}"
            );
            return Ok(());
        }
    };

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

    // 探活搬到后台 —— 现在 setup 立刻返回，webview 同步初始化，
    // __TAURI_INTERNALS__ 注入及时，前端 detectKind() 不会再误判 web。
    spawn_health_probe();
    Ok(())
}

fn spawn_health_probe() {
    std::thread::Builder::new()
        .name("cyber-backend-probe".into())
        .spawn(|| {
            let started = Instant::now();
            let client = match reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(2))
                .build()
            {
                Ok(c) => c,
                Err(e) => {
                    log::error!("[backend] probe client build failed: {e}");
                    return;
                }
            };
            while started.elapsed() < STARTUP_TIMEOUT {
                match client.get(HEALTH_URL).send() {
                    Ok(resp) if resp.status().is_success() => {
                        log::info!(
                            "[backend] ready in {:?}, status={}",
                            started.elapsed(),
                            resp.status()
                        );
                        return;
                    }
                    Ok(resp) => {
                        log::debug!("[backend] probe non-2xx: {}", resp.status());
                    }
                    Err(_) => {}
                }
                std::thread::sleep(PROBE_INTERVAL);
            }
            log::warn!(
                "[backend] sidecar not ready within {STARTUP_TIMEOUT:?}, frontend will surface 5xx"
            );
        })
        .expect("spawn cyber-backend probe thread");
}

/// Tauri RunEvent::Exit 时调，杀掉 sidecar。
pub fn handle_run_event(app: &AppHandle, event: &RunEvent) {
    if matches!(event, RunEvent::Exit) {
        if let Some(state) = app.try_state::<BackendState>() {
            state.shutdown();
        }
    }
}
