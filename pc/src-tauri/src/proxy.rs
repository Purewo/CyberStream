// CyberStream PC · 全局代理状态 + 持久化。
//
// 两类代理（独立配置）：
//   - app_proxy: API 接口 + 静态资源（封面、字幕等）。同时作用于
//     WebView2（前端 fetch / <img>）和 Rust reqwest（心跳、在线字幕、
//     外部播放器字幕下载）。改完必须**重启进程**：WebView2 的
//     --proxy-server 只在初始化时读一次，运行时改 env 没用
//   - video_proxy: mpv 视频流。每次 loadfile 前从这里取值
//     set_option("http-proxy", ...)，运行时变更对下一次播放生效
//
// 持久化：%APPDATA%\com.purewo.cyberstream\proxy.json，纯 JSON：
//   { "app_proxy": "http://...", "video_proxy": null }
// 选 JSON 文件而不是 webview localStorage：WebView2 的 --proxy-server
// 必须在 builder 早期就喂进去，那时 localStorage 还读不到（catch-22），
// 所以 Rust 自己起一份。

use std::fs;
use std::path::PathBuf;
use std::sync::RwLock;
use std::time::Duration;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ProxyConfig {
    /// API + 静态资源代理（WebView2 + Rust reqwest 共用）。
    /// None / 空串 = 不走代理。
    #[serde(default)]
    pub app_proxy: Option<String>,
    /// 视频流代理（mpv）。和 app_proxy 完全独立。
    #[serde(default)]
    pub video_proxy: Option<String>,
}

static CONFIG: RwLock<ProxyConfig> = RwLock::new(ProxyConfig {
    app_proxy: None,
    video_proxy: None,
});

fn config_path() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA")?;
    let mut p = PathBuf::from(base);
    p.push("com.purewo.cyberstream");
    p.push("proxy.json");
    Some(p)
}

fn normalize(s: Option<String>) -> Option<String> {
    s.map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

/// 进程启动时调用：读配置文件 → 写进 CONFIG → 把 app_proxy 返回给
/// lib.rs 用来设 WebView2 启动参数。失败/缺文件返回 None。
pub fn init_from_disk() -> Option<String> {
    let path = config_path()?;
    let text = fs::read_to_string(&path).ok()?;
    let parsed: ProxyConfig = serde_json::from_str(&text).ok()?;
    let cleaned = ProxyConfig {
        app_proxy: normalize(parsed.app_proxy),
        video_proxy: normalize(parsed.video_proxy),
    };
    let app_proxy = cleaned.app_proxy.clone();
    if let Ok(mut g) = CONFIG.write() {
        *g = cleaned;
    }
    app_proxy
}

fn save_to_disk(cfg: &ProxyConfig) -> Result<(), String> {
    let path = config_path().ok_or_else(|| "无法解析 APPDATA 路径".to_string())?;
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("创建配置目录失败：{e}"))?;
    }
    let text = serde_json::to_string_pretty(cfg).map_err(|e| format!("序列化失败：{e}"))?;
    fs::write(&path, text).map_err(|e| format!("写入 {} 失败：{e}", path.display()))
}

#[tauri::command]
pub fn get_proxy_config() -> ProxyConfig {
    CONFIG.read().map(|g| g.clone()).unwrap_or_default()
}

#[tauri::command]
pub fn set_proxy_config(
    app_proxy: Option<String>,
    video_proxy: Option<String>,
) -> Result<ProxyConfig, String> {
    let cleaned = ProxyConfig {
        app_proxy: normalize(app_proxy),
        video_proxy: normalize(video_proxy),
    };
    save_to_disk(&cleaned)?;
    if let Ok(mut g) = CONFIG.write() {
        *g = cleaned.clone();
    }
    Ok(cleaned)
}

/// 心跳 / 在线字幕 / 外部播放器字幕下载共用的 reqwest builder。读 app_proxy。
/// 代理 URL 解析失败时悄悄走直连——不要因为用户随手输错地址就让心跳整个挂掉。
///
/// 用户没配 app_proxy 时显式 `.no_proxy()`：reqwest 默认会读 HTTP_PROXY/
/// HTTPS_PROXY 环境变量；跟 WebView2 那边的 --proxy-server=direct:// 行为
/// 对齐，避免 v2rayN 等工具偷偷把请求拽走。
pub fn build_http_client(timeout_secs: u64) -> Result<reqwest::blocking::Client, reqwest::Error> {
    let mut builder = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(timeout_secs))
        .user_agent("CyberStreamPC/1.21 (Native Player)");

    let app_proxy = CONFIG.read().ok().and_then(|g| g.app_proxy.clone());
    match app_proxy {
        Some(url) => match reqwest::Proxy::all(url.as_str()) {
            Ok(proxy) => builder = builder.proxy(proxy),
            Err(_) => builder = builder.no_proxy(),
        },
        None => builder = builder.no_proxy(),
    }
    builder.build()
}

/// mpv 在 loadfile 前调用：返回当前 video_proxy URL（None 表示直连）。
pub fn video_proxy_url() -> Option<String> {
    CONFIG.read().ok().and_then(|g| g.video_proxy.clone())
}
