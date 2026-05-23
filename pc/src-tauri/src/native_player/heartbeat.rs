// CyberStream PC 原生播放器 · 心跳上报。
//
// PC 原生窗口期间 webview 不可见、不再走 userService.reportHistory，
// 由这里在独立线程上每 10s POST /api/v1/user/history。契约和前端
// `frontend/src/api/user.ts:79-94` 一致：
//   - 不带 Authorization、不带 Cookie；后端用 device_id 模式识别用户
//   - body: { resource_id, position_sec, total_duration, device_id,
//           device_name, session_id }
//
// 设计：
//   - reqwest::blocking 跑在 std::thread 里，完全独立于 GL/tokio
//   - 主循环把 (time_pos, duration, paused, resource_id) 写进 Mutex
//     快照；心跳线程每 10s 读快照、构造 body、发请求
//   - stop=true 翻转后立刻发一次最终上报再退出，让后端记住断开时位置
//   - 失败只 log，不重试（后端没幂等保证；但 10s 后下一 tick 再来过）

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

/// 主循环写、心跳线程读的共享状态。`resource_id` 也放进来，让切集
/// 时下一个 tick 自然带上新的 id，不需要重启线程。
#[derive(Debug, Clone, Default)]
pub struct ProgressSnapshot {
    pub resource_id: String,
    pub position_sec: f64,
    pub duration_sec: f64,
}

pub struct HeartbeatHandle {
    stop: Arc<AtomicBool>,
    snap: Arc<Mutex<ProgressSnapshot>>,
    join: Option<JoinHandle<()>>,
}

impl HeartbeatHandle {
    /// 主循环每帧调一次：刷快照让心跳线程下次 tick 能拿到最新位置。
    pub fn update(&self, snap: ProgressSnapshot) {
        if let Ok(mut g) = self.snap.lock() {
            *g = snap;
        }
    }

    /// 退出原生窗口前调用：通知线程停下、发最终一次上报、阻塞 join。
    pub fn shutdown(mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(h) = self.join.take() {
            let _ = h.join();
        }
    }
}

/// 启动心跳线程。`api_base` 是 webview 那边 `API_BASE.replace(/\/api$/,'')`
/// 的结果，也就是裸 origin（"https://pw.pioneer.fan:84"），心跳线程
/// 自己拼 `/api/v1/user/history`。
pub fn spawn(
    api_base: String,
    device_id: String,
    device_name: String,
    session_id: String,
    initial: ProgressSnapshot,
) -> HeartbeatHandle {
    let stop = Arc::new(AtomicBool::new(false));
    let snap = Arc::new(Mutex::new(initial));

    let stop_clone = Arc::clone(&stop);
    let snap_clone = Arc::clone(&snap);

    let join = std::thread::Builder::new()
        .name("cyberstream-heartbeat".into())
        .spawn(move || {
            let client = match crate::proxy::build_http_client(8) {
                Ok(c) => c,
                Err(e) => {
                    log::warn!("heartbeat: failed to build reqwest client: {e}");
                    return;
                }
            };

            let url = format!("{}/api/v1/user/history", api_base.trim_end_matches('/'));

            // 主循环：每 10s 一次。退出标志检查间隔细一点（500ms），让
            // 用户关窗口后心跳能尽快结束。
            let mut elapsed_ms = 0_u64;
            const TICK_MS: u64 = 500;
            const PERIOD_MS: u64 = 10_000;
            loop {
                if stop_clone.load(Ordering::Acquire) {
                    break;
                }
                std::thread::sleep(Duration::from_millis(TICK_MS));
                elapsed_ms += TICK_MS;
                if elapsed_ms < PERIOD_MS {
                    continue;
                }
                elapsed_ms = 0;
                post_once(&client, &url, &snap_clone, &device_id, &device_name, &session_id);
            }

            // 退出前的最终上报：让后端记住关窗时位置。
            post_once(&client, &url, &snap_clone, &device_id, &device_name, &session_id);
        })
        .expect("heartbeat thread spawn");

    HeartbeatHandle {
        stop,
        snap,
        join: Some(join),
    }
}

fn post_once(
    client: &reqwest::blocking::Client,
    url: &str,
    snap: &Arc<Mutex<ProgressSnapshot>>,
    device_id: &str,
    device_name: &str,
    session_id: &str,
) {
    let s = match snap.lock() {
        Ok(g) => g.clone(),
        Err(_) => return,
    };
    // duration<=0 说明 mpv 还没探测到时长，跳过；resource_id 空也跳过。
    if s.resource_id.is_empty() || s.duration_sec <= 0.5 {
        return;
    }
    let body = serde_json::json!({
        "resource_id": s.resource_id,
        "position_sec": s.position_sec.max(0.0).floor() as i64,
        "total_duration": s.duration_sec.floor() as i64,
        "device_id": device_id,
        "device_name": device_name,
        "session_id": session_id,
    });
    match client.post(url).json(&body).send() {
        Ok(resp) => {
            if !resp.status().is_success() {
                log::warn!(
                    "heartbeat POST {} returned {}",
                    url,
                    resp.status()
                );
            }
        }
        Err(e) => {
            log::warn!("heartbeat POST failed: {e}");
        }
    }
}
