// PC 外部播放器拉起：直接 spawn 本地 .exe + CLI 参数。
//
// 为什么不直接走 URL scheme：
//   - PotPlayer 的 `potplayer://URL` 只能传视频 URL，没有字幕参数。要预加载
//     字幕必须用 CLI： `PotPlayerMini64.exe <url> /sub="<path>"`。
//   - VLC 的 `vlc://` 大多数发行版根本没注册。带字幕的正经做法是
//     `vlc.exe <url> :sub-file=<path>`，URL scheme 这条路走不通。
//
// 字幕 URL 的坑：PotPlayer / VLC 的 /sub= --sub-file= 原本都是给**本地文件路径**
// 用的。HTTP URL 在 PotPlayer 里直接不识别（看着像挂起），在 VLC 3.x 里会被
// 当成 MRL 输入再 URL-encode 一次，输出形如 file:///CWD/https%3A%2F%2F...
// 所以这里先用 reqwest::blocking 把字幕拽到 std::env::temp_dir() 里，再把本地
// 路径喂给 .exe。临时文件名带 resource 哈希，重复拉同一条字幕能命中缓存。
//
// 找不到 .exe 时返回 fallback_required，前端走 URL scheme 兜底。

use std::fs;
use std::path::PathBuf;
use std::process::Command;

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LaunchRequest {
    pub player: String,        // "potplayer" | "vlc"
    pub stream_url: String,
    #[serde(default)]
    pub subtitle_url: Option<String>,
    #[serde(default)]
    pub start_time: Option<f64>, // 秒数；目前 PotPlayer 走 /seek=hh:mm:ss，VLC 走 :start-time
}

#[derive(Debug, serde::Serialize)]
pub struct LaunchResponse {
    pub launched: bool,
    pub method: String,        // "exe" | "url_scheme" | "fallback_required"
    pub message: Option<String>,
    pub exe_path: Option<String>,
    pub subtitle_path: Option<String>,
}

#[tauri::command]
pub async fn launch_external_player(req: LaunchRequest) -> Result<LaunchResponse, String> {
    let player = req.player.to_ascii_lowercase();
    if req.stream_url.trim().is_empty() {
        return Err("stream_url 为空".to_string());
    }

    // 把字幕 URL 落成本地临时文件；下载失败就回 None，让 .exe 不带字幕启动。
    let subtitle_path = req
        .subtitle_url
        .as_deref()
        .filter(|s| !s.trim().is_empty())
        .and_then(|u| download_subtitle_to_temp(u).ok());

    match player.as_str() {
        "potplayer" => launch_potplayer(&req, subtitle_path.as_deref()),
        "vlc" => launch_vlc(&req, subtitle_path.as_deref()),
        other => Err(format!("不支持的外部播放器：{other}")),
    }
}

/// 拉字幕到 temp 目录，文件名 = cyberstream_sub_<hash>.<ext>。
/// 返回本地绝对路径或下载失败的错误（向上传播由调用方决定要不要无字幕启动）。
fn download_subtitle_to_temp(url: &str) -> Result<PathBuf, String> {
    let parsed = reqwest::Url::parse(url).map_err(|e| format!("字幕 URL 解析失败：{e}"))?;
    // 用整个 URL（去 fragment）做 hash key —— 同一条字幕重复拉就命中缓存。
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    use std::hash::{Hash, Hasher};
    parsed.as_str().hash(&mut hasher);
    let key = hasher.finish();

    // 推断扩展名优先级：
    //   1. URL path 末尾（cyber.srt 这种静态文件）
    //   2. query 里的 format=xxx（后端动态字幕 URL 通常是
    //      /resources/.../stream?subtitle_id=...&format=sup 这种形态，
    //      path 末尾根本没扩展名）
    //   3. 默认 .srt
    // 三者都按白名单（srt/ass/ssa/vtt/sub/sup/idx）做正字校验，避免把奇怪后缀
    // 当成扩展名。早期版本只把 vtt 单独认了一个，sup 字幕被错命名成 .srt
    // 给 PotPlayer，能加载但用户看到 .srt 后缀会误以为字幕格式不对。
    const KNOWN_EXTS: [&str; 7] = ["srt", "ass", "ssa", "vtt", "sub", "sup", "idx"];
    let path_ext = parsed
        .path_segments()
        .and_then(|mut s| s.next_back())
        .and_then(|name| name.rsplit('.').next())
        .filter(|e| KNOWN_EXTS.iter().any(|known| known.eq_ignore_ascii_case(e)))
        .map(|s| s.to_ascii_lowercase());
    let query_ext = {
        let q: std::collections::HashMap<_, _> = parsed.query_pairs().into_owned().collect();
        q.get("format")
            .map(|s| s.to_ascii_lowercase())
            .filter(|s| KNOWN_EXTS.iter().any(|k| k == s))
    };
    let ext = path_ext.or(query_ext).unwrap_or_else(|| "srt".to_string());

    let path = std::env::temp_dir().join(format!("cyberstream_sub_{key:016x}.{ext}"));
    if path.exists() && path.metadata().map(|m| m.len() > 0).unwrap_or(false) {
        return Ok(path);
    }

    // blocking client：launch_external_player 已经是 async 命令，直接 spawn_blocking。
    let url = url.to_string();
    let path_clone = path.clone();
    let result = std::thread::spawn(move || -> Result<(), String> {
        let resp = crate::proxy::build_http_client(15)
            .map_err(|e| format!("reqwest 构造失败：{e}"))?
            .get(&url)
            .send()
            .map_err(|e| format!("字幕下载失败：{e}"))?;
        if !resp.status().is_success() {
            return Err(format!("字幕下载 HTTP {}", resp.status()));
        }
        let bytes = resp.bytes().map_err(|e| format!("字幕读取失败：{e}"))?;
        fs::write(&path_clone, &bytes).map_err(|e| format!("写临时文件失败：{e}"))?;
        Ok(())
    })
    .join()
    .map_err(|_| "字幕下载线程 panic".to_string())?;
    result?;
    Ok(path)
}

fn launch_potplayer(req: &LaunchRequest, subtitle_path: Option<&std::path::Path>) -> Result<LaunchResponse, String> {
    let exe = match locate_potplayer() {
        Some(p) => p,
        None => {
            return Ok(LaunchResponse {
                launched: false,
                method: "fallback_required".to_string(),
                message: Some("未找到 PotPlayer，前端可走 URL scheme 兜底".to_string()),
                exe_path: None,
                subtitle_path: None,
            });
        }
    };

    // PotPlayer CLI（官方 CmdLine64.txt，安装目录自带；中文版原文）：
    //   PotPlayerMini64.exe "文件路径" [参数]
    //   /sub=["]字幕文件["]    -- 引号可选，官方明确说支持 path 或 URL
    //   /seek=hh:mm:ss.ms      -- 起始时间（也可纯秒数）
    //   /current               -- 在当前播放器中打开（忽略禁止多重执行选项）
    //
    // 已知限制：CLI 没有"强制选中外挂字幕作为默认"的开关。/sub= 只负责"加载"，
    // 显示哪条字幕由 PotPlayer 偏好设置「字幕 → 字幕语言优先级」决定。当视频
    // 含内嵌字幕轨时，PotPlayer 默认偏向内嵌，会忽略我们的外挂。用户可在
    // PotPlayer 设置「F5 → 字幕 → 缺省语言」里把"外挂字幕优先"勾上来一劳永逸；
    // 我们这边能做的只是把字幕**加载到候选列表**，让用户右键能切到。
    let mut cmd = Command::new(&exe);
    cmd.arg("/current");
    cmd.arg(&req.stream_url);
    if let Some(p) = subtitle_path {
        cmd.arg(format!("/sub={}", p.display()));
    }
    if let Some(t) = req.start_time {
        if t > 0.0 {
            cmd.arg(format!("/seek={}", format_hms(t)));
        }
    }

    spawn_detached(&mut cmd, &exe, subtitle_path)
}

fn launch_vlc(req: &LaunchRequest, subtitle_path: Option<&std::path::Path>) -> Result<LaunchResponse, String> {
    let exe = match locate_vlc() {
        Some(p) => p,
        None => {
            return Ok(LaunchResponse {
                launched: false,
                method: "fallback_required".to_string(),
                message: Some("未找到 VLC，前端可走 URL scheme 兜底".to_string()),
                exe_path: None,
                subtitle_path: None,
            });
        }
    };

    // VLC CLI（≥ 3.0）：
    //   --no-video-title-show     -- 不在视频左上闪标题
    //   <stream_url>              -- 视频 MRL
    //   :sub-file=<path>          -- 字幕（MRL 选项，紧跟在视频 URL 后面，
    //                                带冒号前缀；--sub-file= 全局变量在 3.x 里
    //                                对 HTTP URL 有 bug，会反而把字幕 URL 当
    //                                视频输入）
    //   :start-time=<sec>         -- 起始秒数（同样是 MRL 选项）
    let mut cmd = Command::new(&exe);
    cmd.arg("--no-video-title-show");
    cmd.arg(&req.stream_url);
    if let Some(p) = subtitle_path {
        cmd.arg(format!(":sub-file={}", p.display()));
    }
    if let Some(t) = req.start_time {
        if t > 0.0 {
            cmd.arg(format!(":start-time={}", t.round() as i64));
        }
    }

    spawn_detached(&mut cmd, &exe, subtitle_path)
}

/// 把秒数格式化成 HH:MM:SS（PotPlayer /seek= 要求的格式）。
fn format_hms(sec: f64) -> String {
    let total = sec.max(0.0).round() as i64;
    let h = total / 3600;
    let m = (total % 3600) / 60;
    let s = total % 60;
    format!("{:02}:{:02}:{:02}", h, m, s)
}

/// spawn 子进程并立刻 return —— 不等它退出。Windows 下用 CREATE_NEW_PROCESS_GROUP
/// 让外部播放器跟我们解耦：CyberStream 退出时不连带杀掉它。
#[cfg(windows)]
fn spawn_detached(
    cmd: &mut Command,
    exe: &PathBuf,
    subtitle_path: Option<&std::path::Path>,
) -> Result<LaunchResponse, String> {
    use std::os::windows::process::CommandExt;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
    const DETACHED_PROCESS: u32 = 0x00000008;
    cmd.creation_flags(CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS);
    cmd.spawn()
        .map_err(|e| format!("启动 {} 失败：{}", exe.display(), e))?;
    Ok(LaunchResponse {
        launched: true,
        method: "exe".to_string(),
        message: None,
        exe_path: Some(exe.display().to_string()),
        subtitle_path: subtitle_path.map(|p| p.display().to_string()),
    })
}

#[cfg(not(windows))]
fn spawn_detached(
    cmd: &mut Command,
    exe: &PathBuf,
    subtitle_path: Option<&std::path::Path>,
) -> Result<LaunchResponse, String> {
    cmd.spawn()
        .map_err(|e| format!("启动 {} 失败：{}", exe.display(), e))?;
    Ok(LaunchResponse {
        launched: true,
        method: "exe".to_string(),
        message: None,
        exe_path: Some(exe.display().to_string()),
        subtitle_path: subtitle_path.map(|p| p.display().to_string()),
    })
}

// ────────────────────────────── 定位 .exe ──────────────────────────────

fn locate_potplayer() -> Option<PathBuf> {
    // 1) Windows 注册表（Daum 官方安装会写）
    #[cfg(windows)]
    {
        for path in registry_uninstall_lookup("PotPlayer") {
            if path.exists() {
                return Some(path);
            }
        }
        for hive in [r"HKLM\SOFTWARE\DAUM\PotPlayer64", r"HKLM\SOFTWARE\DAUM\PotPlayer"] {
            if let Some(p) = registry_query(hive, "ProgramPath") {
                let pb = PathBuf::from(p);
                if pb.exists() {
                    return Some(pb);
                }
            }
        }
    }

    // 2) 常见安装目录
    let candidates: &[&str] = &[
        r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
        r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe",
        r"C:\Program Files\DAUM\PotPlayer\PotPlayer.exe",
        r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
        r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayer.exe",
    ];
    for c in candidates {
        let pb = PathBuf::from(c);
        if pb.exists() {
            return Some(pb);
        }
    }

    // 3) PATH 兜底
    which("PotPlayerMini64.exe").or_else(|| which("PotPlayer.exe"))
}

fn locate_vlc() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        for path in registry_uninstall_lookup("VLC media player") {
            if path.exists() {
                return Some(path);
            }
        }
        if let Some(p) = registry_query(r"HKLM\SOFTWARE\VideoLAN\VLC", "InstallDir") {
            let pb = PathBuf::from(p).join("vlc.exe");
            if pb.exists() {
                return Some(pb);
            }
        }
    }

    let candidates: &[&str] = &[
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        r"/Applications/VLC.app/Contents/MacOS/VLC",
        r"/usr/bin/vlc",
    ];
    for c in candidates {
        let pb = PathBuf::from(c);
        if pb.exists() {
            return Some(pb);
        }
    }

    which("vlc.exe").or_else(|| which("vlc"))
}

/// 在 PATH 里查找可执行文件。返回首个匹配的绝对路径。
fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let p = dir.join(name);
        if p.is_file() {
            return Some(p);
        }
    }
    None
}

/// Windows 注册表 query。失败返回 None。用 reg.exe 命令避开 winreg crate 依赖。
#[cfg(windows)]
fn registry_query(hive_path: &str, value: &str) -> Option<String> {
    let out = Command::new("reg")
        .arg("query")
        .arg(hive_path)
        .arg("/v")
        .arg(value)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    // 输出形如：     ProgramPath    REG_SZ    C:\path\to\PotPlayer.exe
    for line in stdout.lines() {
        let trimmed = line.trim();
        if let Some(idx) = trimmed.find("REG_SZ") {
            let v = trimmed[idx + "REG_SZ".len()..].trim();
            if !v.is_empty() {
                return Some(v.to_string());
            }
        }
        if let Some(idx) = trimmed.find("REG_EXPAND_SZ") {
            let v = trimmed[idx + "REG_EXPAND_SZ".len()..].trim();
            if !v.is_empty() {
                return Some(v.to_string());
            }
        }
    }
    None
}

/// 扫 Uninstall 子键找 DisplayName 包含 needle 的应用，返回它的 InstallLocation
/// 下可能的 .exe 路径（PotPlayerMini64.exe / vlc.exe 等）。
#[cfg(windows)]
fn registry_uninstall_lookup(needle: &str) -> Vec<PathBuf> {
    let mut results = Vec::new();
    for root in [
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    ] {
        let out = Command::new("reg")
            .arg("query")
            .arg(root)
            .arg("/s")
            .arg("/f")
            .arg(needle)
            .arg("/d")
            .arg("/k")
            .output();
        let out = match out {
            Ok(v) if v.status.success() => v,
            _ => continue,
        };
        let stdout = String::from_utf8_lossy(&out.stdout);
        // 简化：按行扫子键路径，再分别 query InstallLocation / DisplayIcon / UninstallString
        for line in stdout.lines() {
            let line = line.trim();
            if !line.starts_with(r"HKEY_") {
                continue;
            }
            // 命中条目：抽 InstallLocation，再拼上常见 exe 名
            if let Some(loc) = registry_query(line, "InstallLocation") {
                let loc = loc.trim_matches('"').trim().to_string();
                if loc.is_empty() {
                    continue;
                }
                let base = PathBuf::from(loc);
                for exe_name in &[
                    "PotPlayerMini64.exe",
                    "PotPlayer64.exe",
                    "PotPlayer.exe",
                    "PotPlayerMini.exe",
                    "vlc.exe",
                ] {
                    let pb = base.join(exe_name);
                    if pb.exists() {
                        results.push(pb);
                    }
                }
            }
            // DisplayIcon 也常被设成 .exe 路径
            if let Some(icon) = registry_query(line, "DisplayIcon") {
                let icon = icon
                    .trim_matches('"')
                    .split(',')
                    .next()
                    .unwrap_or("")
                    .trim()
                    .to_string();
                if !icon.is_empty() {
                    let pb = PathBuf::from(icon);
                    if pb.exists() {
                        results.push(pb);
                    }
                }
            }
        }
    }
    results
}

#[cfg(not(windows))]
fn registry_query(_: &str, _: &str) -> Option<String> {
    None
}

#[cfg(not(windows))]
fn registry_uninstall_lookup(_: &str) -> Vec<PathBuf> {
    Vec::new()
}
