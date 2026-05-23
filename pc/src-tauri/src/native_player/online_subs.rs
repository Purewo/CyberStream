// CyberStream PC 原生播放器 · 在线字幕 search/download/bind 客户端。
//
// 后端契约：
//   - 搜索   GET  /api/v1/resources/{resource_id}/subtitles/online/search
//   - 下载   POST /api/v1/resources/{resource_id}/subtitles/online/download
//             body { candidate_id, format? }
//             响应 = 字幕文件原文（octet-stream / x-subrip / vtt 等）
//   - 绑定   POST /api/v1/resources/{resource_id}/subtitles/online/bind
//             body { candidate_id, confirm: true, format? }
//             响应 OnlineSubtitleBindData（含新 subtitle_id + url）
//
// 全部走独立 std::thread + reqwest::blocking，跟 heartbeat 一样不沾 GL/tokio。
// 调用方持 Arc<Mutex<OnlineSubState>>，worker 完成后 lock 一次写入。

use std::sync::{Arc, Mutex};

use crate::native_player::controller::{OnlineCandidate, OnlineSubState, SearchPhase};

/// 启动一次搜索 worker。前端关键词来自用户输入或主循环用 movie.title 兜底。
/// 完成后会把结果写回 `state` 的 Mutex。
pub fn spawn_search(
    api_base: String,
    resource_id: String,
    keyword: String,
    state: Arc<Mutex<OnlineSubState>>,
) {
    if let Ok(mut g) = state.lock() {
        g.search = SearchPhase::Loading;
    }
    std::thread::Builder::new()
        .name("cyberstream-online-sub-search".into())
        .spawn(move || {
            let client = match build_client() {
                Ok(c) => c,
                Err(e) => {
                    fail(&state, format!("build client: {e}"));
                    return;
                }
            };
            let url = format!(
                "{}/api/v1/resources/{}/subtitles/online/search",
                api_base.trim_end_matches('/'),
                resource_id
            );
            let req = client.get(&url).query(&[("keyword", keyword.as_str())]);
            let resp = match req.send() {
                Ok(r) => r,
                Err(e) => {
                    fail(&state, format!("请求失败: {e}"));
                    return;
                }
            };
            if !resp.status().is_success() {
                fail(&state, format!("HTTP {}", resp.status()));
                return;
            }
            let json: serde_json::Value = match resp.json() {
                Ok(j) => j,
                Err(e) => {
                    fail(&state, format!("解析 JSON: {e}"));
                    return;
                }
            };
            let candidates = parse_candidates(&json);
            if let Ok(mut g) = state.lock() {
                g.search = SearchPhase::Loaded(candidates);
            }
        })
        .expect("online-sub search spawn");
}

/// 预览 worker —— download 字节、写本地临时文件，然后在 GL 主循环里
/// `mpv sub-add <tmp_path> select`。返回的临时路径通过 oneshot channel
/// 给主循环拿；主循环负责清理（关窗时丢弃即可，OS 会清 temp）。
pub fn spawn_preview(
    api_base: String,
    resource_id: String,
    candidate_id: String,
    label: String,
    state: Arc<Mutex<OnlineSubState>>,
    on_ready: std::sync::mpsc::Sender<PreviewReady>,
) {
    if let Ok(mut g) = state.lock() {
        g.busy_candidate = Some(candidate_id.clone());
        g.last_message = Some(format!("正在下载预览：{label}…"));
    }
    let cid_for_clear = candidate_id.clone();
    std::thread::Builder::new()
        .name("cyberstream-online-sub-preview".into())
        .spawn(move || {
            let result = do_download(&api_base, &resource_id, &candidate_id);
            // 不论成败，先清掉 busy 标志
            let outcome = match result {
                Ok(bytes) => match write_temp_subtitle(&candidate_id, &bytes) {
                    Ok(path) => {
                        let msg = format!("已预览：{label}（未绑定）");
                        Some((path, msg))
                    }
                    Err(e) => {
                        if let Ok(mut g) = state.lock() {
                            g.last_message = Some(format!("写入临时文件失败：{e}"));
                        }
                        None
                    }
                },
                Err(e) => {
                    if let Ok(mut g) = state.lock() {
                        g.last_message = Some(format!("预览失败：{e}"));
                    }
                    None
                }
            };
            if let Ok(mut g) = state.lock() {
                if g.busy_candidate.as_deref() == Some(cid_for_clear.as_str()) {
                    g.busy_candidate = None;
                }
            }
            if let Some((path, msg)) = outcome {
                if let Ok(mut g) = state.lock() {
                    g.last_message = Some(msg);
                }
                let _ = on_ready.send(PreviewReady {
                    candidate_id: cid_for_clear,
                    path,
                });
            }
        })
        .expect("online-sub preview spawn");
}

/// 绑定 worker —— POST /bind?confirm=true，把返回的 subtitle (id+url) 通过 channel
/// 送回主循环；主循环把它注入 state.movie.resources 当前条目，跟初始外挂字幕
/// 走完全一样的渲染路径。
pub fn spawn_bind(
    api_base: String,
    resource_id: String,
    candidate_id: String,
    label: String,
    state: Arc<Mutex<OnlineSubState>>,
    on_ready: std::sync::mpsc::Sender<BindReady>,
) {
    if let Ok(mut g) = state.lock() {
        g.busy_candidate = Some(candidate_id.clone());
        g.last_message = Some(format!("正在绑定：{label}…"));
    }
    let cid_for_clear = candidate_id.clone();
    std::thread::Builder::new()
        .name("cyberstream-online-sub-bind".into())
        .spawn(move || {
            let result = do_bind(&api_base, &resource_id, &candidate_id);
            let outcome = match result {
                Ok(bind) => {
                    if let Ok(mut g) = state.lock() {
                        g.last_message = Some(format!("绑定成功：{label}"));
                    }
                    Some(bind)
                }
                Err(e) => {
                    if let Ok(mut g) = state.lock() {
                        g.last_message = Some(format!("绑定失败：{e}"));
                    }
                    None
                }
            };
            if let Ok(mut g) = state.lock() {
                if g.busy_candidate.as_deref() == Some(cid_for_clear.as_str()) {
                    g.busy_candidate = None;
                }
            }
            if let Some(bind) = outcome {
                let _ = on_ready.send(bind);
            }
        })
        .expect("online-sub bind spawn");
}

#[derive(Debug)]
pub struct PreviewReady {
    pub candidate_id: String,
    pub path: String,
}

#[derive(Debug)]
pub struct BindReady {
    pub subtitle_id: String,
    pub url: String,
    pub label: Option<String>,
    /// 后端 1.21+ 给的更可读的展示名（release 标题）。UI 优先用它。
    pub display_name: Option<String>,
    pub format: Option<String>,
}

/// 删除完成回执 —— 不论成败都 send 一条，主循环按 ok 决定是真摘字幕条目
/// 还是只清 pending_delete_sid 状态行 + 弹一条错误消息。
#[derive(Debug)]
pub struct DeleteReady {
    pub subtitle_id: String,
    pub ok: bool,
    pub message: Option<String>,
}

/// 删除 worker —— DELETE /api/v1/resources/{rid}/subtitles/{sid}。
/// 后端只允许删 source=online_bound / manual_upload；sidecar 会回 400。
/// 我们 PC 端目前不显示 source 字段，按用户要求只在「已绑定」段挂这个按钮，
/// 调用前提就是用户操作的字幕一定是绑定来的，按 400 当成普通错误显示即可。
pub fn spawn_delete(
    api_base: String,
    resource_id: String,
    subtitle_id: String,
    state: Arc<Mutex<OnlineSubState>>,
    on_ready: std::sync::mpsc::Sender<DeleteReady>,
) {
    if let Ok(mut g) = state.lock() {
        g.last_message = Some(format!("正在删除字幕…"));
    }
    std::thread::Builder::new()
        .name("cyberstream-online-sub-delete".into())
        .spawn(move || {
            let result = do_delete(&api_base, &resource_id, &subtitle_id);
            let (ok, msg) = match result {
                Ok(()) => (true, None),
                Err(e) => (false, Some(e)),
            };
            if let Ok(mut g) = state.lock() {
                g.last_message = Some(if ok {
                    "字幕已删除".to_string()
                } else {
                    format!("删除失败：{}", msg.clone().unwrap_or_default())
                });
            }
            let _ = on_ready.send(DeleteReady {
                subtitle_id,
                ok,
                message: msg,
            });
        })
        .expect("online-sub delete spawn");
}

// ---- helpers ----

fn build_client() -> Result<reqwest::blocking::Client, reqwest::Error> {
    crate::proxy::build_http_client(20)
}

fn fail(state: &Arc<Mutex<OnlineSubState>>, msg: String) {
    if let Ok(mut g) = state.lock() {
        g.search = SearchPhase::Error(msg);
    }
}

fn parse_candidates(v: &serde_json::Value) -> Vec<OnlineCandidate> {
    // 后端响应包络：{ code, msg, data: { items: [...] } } 或类似结构。
    // 走宽松路径——找到 "items" 数组就用它，否则尝试 root。
    let arr = v
        .pointer("/data/items")
        .or_else(|| v.pointer("/data"))
        .or_else(|| v.pointer("/items"))
        .and_then(|x| x.as_array())
        .cloned()
        .unwrap_or_default();
    let mut out = Vec::with_capacity(arr.len());
    for item in arr {
        let candidate_id = item
            .get("candidate_id")
            .or_else(|| item.get("id"))
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string();
        if candidate_id.is_empty() {
            continue;
        }
        let source = item
            .get("source")
            .or_else(|| item.get("provider"))
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string();
        let language = item
            .get("language")
            .and_then(|l| {
                if l.is_string() {
                    l.as_str().map(|s| s.to_string())
                } else {
                    l.get("name")
                        .or_else(|| l.get("code"))
                        .and_then(|x| x.as_str())
                        .map(|s| s.to_string())
                }
            })
            .or_else(|| {
                item.get("lang")
                    .and_then(|x| x.as_str())
                    .map(|s| s.to_string())
            });
        let format = item
            .get("format")
            .and_then(|x| x.as_str())
            .map(|s| s.to_string());
        // label 优先级：display_name → title → filename → label → "<source>·<lang>"
        // display_name 是后端 1.21+ 给的 release 标题（去扩展名），最可读，
        // 落在 release 名而不是字幕站自己的"Chinese Simplified + English ASS"。
        let label = item
            .get("display_name")
            .or_else(|| item.get("title"))
            .or_else(|| item.get("filename"))
            .or_else(|| item.get("label"))
            .and_then(|x| x.as_str())
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                let l = language.clone().unwrap_or_else(|| "?".into());
                format!("{source} · {l}")
            });
        out.push(OnlineCandidate {
            candidate_id,
            label,
            source,
            language,
            format,
        });
    }
    out
}

fn do_download(api_base: &str, resource_id: &str, candidate_id: &str) -> Result<Vec<u8>, String> {
    let client = build_client().map_err(|e| e.to_string())?;
    let url = format!(
        "{}/api/v1/resources/{}/subtitles/online/download",
        api_base.trim_end_matches('/'),
        resource_id
    );
    let resp = client
        .post(&url)
        .json(&serde_json::json!({ "candidate_id": candidate_id }))
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.bytes()
        .map(|b| b.to_vec())
        .map_err(|e| e.to_string())
}

fn do_bind(api_base: &str, resource_id: &str, candidate_id: &str) -> Result<BindReady, String> {
    let client = build_client().map_err(|e| e.to_string())?;
    let url = format!(
        "{}/api/v1/resources/{}/subtitles/online/bind",
        api_base.trim_end_matches('/'),
        resource_id
    );
    let resp = client
        .post(&url)
        .json(&serde_json::json!({
            "candidate_id": candidate_id,
            "confirm": true
        }))
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    let v: serde_json::Value = resp.json().map_err(|e| e.to_string())?;
    // 后端 envelope: { data: { subtitle: ResourceSubtitleItem } } 或 data.subtitle 直挂。
    // 字段：subtitle.id / subtitle.url / subtitle.label / subtitle.format
    let sub = v
        .pointer("/data/subtitle")
        .or_else(|| v.pointer("/subtitle"))
        .or_else(|| v.pointer("/data"))
        .ok_or_else(|| "响应里没有 subtitle 字段".to_string())?;
    let id = sub
        .get("id")
        .and_then(|x| x.as_str())
        .ok_or_else(|| "缺少 subtitle.id".to_string())?
        .to_string();
    let raw_url = sub
        .get("url")
        .and_then(|x| x.as_str())
        .ok_or_else(|| "缺少 subtitle.url".to_string())?
        .to_string();
    let absolute_url = resolve_absolute(api_base, &raw_url);
    let label = sub
        .get("label")
        .or_else(|| sub.get("filename"))
        .and_then(|x| x.as_str())
        .map(|s| s.to_string());
    let display_name = sub
        .get("display_name")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string());
    let format = sub
        .get("format")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string());
    Ok(BindReady {
        subtitle_id: id,
        url: absolute_url,
        label,
        display_name,
        format,
    })
}

fn do_delete(api_base: &str, resource_id: &str, subtitle_id: &str) -> Result<(), String> {
    let client = build_client().map_err(|e| e.to_string())?;
    let url = format!(
        "{}/api/v1/resources/{}/subtitles/{}",
        api_base.trim_end_matches('/'),
        resource_id,
        subtitle_id,
    );
    let resp = client.delete(&url).send().map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    Ok(())
}

/// 后端给的 url 一般是 `/api/v1/resources/.../stream?subtitle_id=...` 这种相对
/// 路径。mpv 必须拿到绝对地址才能 GET，所以这里手动拼一下。逻辑跟前端
/// `App.tsx::resolveSubUrl` 完全对齐。
fn resolve_absolute(api_base: &str, url: &str) -> String {
    if url.starts_with("http://") || url.starts_with("https://") {
        return url.to_string();
    }
    let host = api_base.trim_end_matches('/');
    if let Some(rest) = url.strip_prefix("/api/") {
        format!("{host}/{rest}")
    } else if url.starts_with('/') {
        format!("{host}{url}")
    } else {
        format!("{host}/{url}")
    }
}

fn write_temp_subtitle(candidate_id: &str, bytes: &[u8]) -> std::io::Result<String> {
    use std::io::Write;
    // 候选 id 形如 "subhd:abc123" / "srtku:42" —— 冒号 Windows 不让做文件名，
    // 替换成 _。后缀用 .srt 让 mpv 不用嗅探（多数源都是 srt；mpv 自己也能解析
    // ass / vtt，错给个 .srt 后缀也 OK，mpv 实际看 magic）。
    let safe = candidate_id.replace(|c: char| !c.is_ascii_alphanumeric(), "_");
    let mut dir = std::env::temp_dir();
    dir.push("cyberstream-pc-subs");
    std::fs::create_dir_all(&dir)?;
    dir.push(format!("{safe}.srt"));
    {
        let mut f = std::fs::File::create(&dir)?;
        f.write_all(bytes)?;
    }
    Ok(dir.to_string_lossy().into_owned())
}
