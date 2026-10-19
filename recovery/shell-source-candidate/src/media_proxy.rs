// CyberStream PC · 本地媒体代理
//
// 给外部播放器（PotPlayer / VLC）做 User-Agent 改写。
//
// 为什么需要：
//   - 百度网盘的 stream URL 经过几层 302 后，最终的 d.pcs.baidu.com 直链
//     需要请求方带特定 UA（pan.baidu.com / netdisk）才返回视频流；普通
//     播放器 UA 上去会拿到 403 / 反爬页
//   - mpv 通过 http-header-fields 选项就能改 UA（已经在 native_player
//     里走通），但 PotPlayer / VLC 都只接受 CLI 文件路径或 URL，**没法
//     传 HTTP header**
//   - 所以唯一通用解：在 PC 本地起 axum HTTP server，把原始 stream URL
//     包成 http://127.0.0.1:<port>/stream?u=<encoded>&ua=<encoded>，
//     播放器请求这条本地 URL，本地 server 用指定 UA 拉上游、跟 302、
//     透传 Range，把响应流回吐
//
// 端口：第一次启动时让 OS 随机分配（127.0.0.1:0），缓存到 PORT。前端调
// `media_proxy_url` 命令拿当前 base URL（http://127.0.0.1:<port>）。
//
// 安全：监听 127.0.0.1 only，外网/局域网无法访问。但仍然校验上游 URL
// scheme 必须是 http(s)，避免 file:/// 之类协议跳出来。

use std::sync::OnceLock;

use axum::{
    body::Body,
    extract::Query,
    http::{header, HeaderMap, HeaderValue, Method, StatusCode},
    response::{IntoResponse, Response},
    routing::{any, get},
    Router,
};
use serde::Deserialize;

/// 全局缓存的代理 base URL（http://127.0.0.1:<port>）。第一次 start()
/// 后填上，后续 media_proxy_url 命令直接读这个。Option 用 None 表示
/// "还没启动 / 启动失败"，前端拿到 None 时降级到原始 URL。
static BASE_URL: OnceLock<String> = OnceLock::new();

#[derive(Debug, Deserialize)]
struct StreamQuery {
    /// 上游 URL（必填）。前端要 percent-encode 整个 URL 再塞进来。
    u: String,
    /// 改写后的 User-Agent（可选）。空表示不改写，沿用 reqwest 默认。
    /// 百度网盘需要 `pan.baidu.com`，其他场景可以不传。
    #[serde(default)]
    ua: Option<String>,
}

/// 启动监听 127.0.0.1 随机端口的 axum server。
///
/// 在独立 tokio 任务里跑，主进程不阻塞。返回 base URL（http://127.0.0.1:<port>）
/// 供 BASE_URL 缓存；如果 bind 失败返回 None，外部播放器路径降级到原始 URL
/// （播百度时一定 403，但比直接崩好）。
pub async fn start() -> Option<String> {
    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/stream", any(stream_handler));

    // 0 端口让 OS 选一个空闲的；不写死避免跟用户其他服务撞。
    let listener = match tokio::net::TcpListener::bind("127.0.0.1:0").await {
        Ok(l) => l,
        Err(e) => {
            log::warn!("[media_proxy] bind 127.0.0.1:0 failed: {e}");
            return None;
        }
    };
    let local = match listener.local_addr() {
        Ok(a) => a,
        Err(e) => {
            log::warn!("[media_proxy] local_addr failed: {e}");
            return None;
        }
    };
    let base = format!("http://{}", local);
    log::info!("[media_proxy] listening on {base}");

    // 把 base 缓存起来，命令侧读它。OnceLock 只接受第一次写入；同一进程
    // 内重复调用 start() 会忽略后续值（不应该发生，但防御一下）。
    let _ = BASE_URL.set(base.clone());

    tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app).await {
            log::error!("[media_proxy] serve exited with error: {e}");
        }
    });
    Some(base)
}

/// 当前代理 base URL。前端外播前调一次拿到 `http://127.0.0.1:<port>`，
/// 然后自己拼 `/stream?u=...&ua=...`。
#[tauri::command]
pub fn media_proxy_url() -> Option<String> {
    BASE_URL.get().cloned()
}

/// `/stream` 处理器：
///   1. 校验上游 URL scheme 为 http/https
///   2. 透传客户端的 Range header（视频拖动）
///   3. 用 reqwest async client 拉上游，带改写后的 UA + 跟 302
///   4. 把上游 status / 关键 header / body stream 原样回吐
async fn stream_handler(
    method: Method,
    headers: HeaderMap,
    Query(q): Query<StreamQuery>,
) -> Result<Response, ProxyError> {
    let upstream_url = q.u.clone();
    if !is_safe_scheme(&upstream_url) {
        return Err(ProxyError::BadRequest("upstream scheme must be http(s)".into()));
    }

    // reqwest 默认会跟 302。百度网盘 d.pcs 链条需要每一跳都带改写后的
    // UA，redirect_policy::limited 默认透传 header，所以这里不用手动
    // 维护跳转。
    let client = reqwest::Client::builder()
        .danger_accept_invalid_certs(false)
        .redirect(reqwest::redirect::Policy::limited(8))
        .build()
        .map_err(|e| ProxyError::Internal(format!("reqwest build: {e}")))?;

    let mut req = match method {
        Method::HEAD => client.head(&upstream_url),
        _ => client.get(&upstream_url),
    };

    // UA 改写：q.ua 非空就强制覆盖；空时让 reqwest 用默认（reqwest/x.y）。
    if let Some(ua) = q.ua.as_deref().filter(|s| !s.trim().is_empty()) {
        req = req.header(header::USER_AGENT, ua);
    }

    // 透传 Range / If-Range / If-None-Match / Accept 等播放器要的 header。
    // 不透传 Host（reqwest 自己根据 URL 写）；不透传 Authorization（避免把
    // 客户端浏览器的认证泄漏给百度上游）。白名单足够，黑名单容易漏。
    for (k, v) in headers.iter() {
        let name = k.as_str();
        if matches!(
            name,
            "range" | "if-range" | "if-none-match" | "if-modified-since" | "accept"
        ) {
            if let Ok(s) = v.to_str() {
                req = req.header(k.as_str(), s);
            }
        }
    }

    let upstream = req
        .send()
        .await
        .map_err(|e| ProxyError::Upstream(format!("upstream send: {e}")))?;

    let status = upstream.status();
    // axum 0.7 用 http::StatusCode；reqwest 0.12 也是 http 1.x。直接 from_u16。
    let resp_status =
        StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);

    // 透传跟视频流相关的 header；丢掉 Connection / Transfer-Encoding /
    // Content-Encoding（让 hyper 自己重新决定 chunked 之类）。
    let mut out = Response::builder().status(resp_status);
    for (k, v) in upstream.headers().iter() {
        let name = k.as_str().to_ascii_lowercase();
        if matches!(
            name.as_str(),
            "content-type"
                | "content-length"
                | "content-range"
                | "accept-ranges"
                | "last-modified"
                | "etag"
                | "cache-control"
        ) {
            if let Some(builder_headers) = out.headers_mut() {
                if let Ok(name_str) = http::HeaderName::from_bytes(k.as_str().as_bytes()) {
                    if let Ok(val_str) =
                        HeaderValue::from_bytes(v.as_bytes())
                    {
                        builder_headers.append(name_str, val_str);
                    }
                }
            }
        }
    }

    // body 走流式，避免把整段视频加载进内存。reqwest 的 bytes_stream
    // 返回 impl Stream<Item = Result<Bytes, reqwest::Error>>；axum
    // Body::from_stream 直接接受。
    let stream = upstream.bytes_stream();
    let body = Body::from_stream(stream);

    out.body(body)
        .map_err(|e| ProxyError::Internal(format!("build response: {e}")))
}

fn is_safe_scheme(url: &str) -> bool {
    let lower = url.to_ascii_lowercase();
    lower.starts_with("http://") || lower.starts_with("https://")
}

/// 内部错误类型。axum IntoResponse 让 handler 直接 `?` 抛错。
enum ProxyError {
    BadRequest(String),
    Upstream(String),
    Internal(String),
}

impl IntoResponse for ProxyError {
    fn into_response(self) -> Response {
        let (status, msg) = match self {
            ProxyError::BadRequest(m) => (StatusCode::BAD_REQUEST, m),
            ProxyError::Upstream(m) => (StatusCode::BAD_GATEWAY, m),
            ProxyError::Internal(m) => (StatusCode::INTERNAL_SERVER_ERROR, m),
        };
        log::warn!("[media_proxy] {status} {msg}");
        (status, msg).into_response()
    }
}
