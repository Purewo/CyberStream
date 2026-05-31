// 跨 webview 边界传递的影片元数据。
//
// 本机 player 的右侧详情面板需要影片标题/简介、季 tabs、集数列表、
// 多源切换。后端契约和前端类型已经存在，但 Rust 单独再调一遍后端
// 既费工又会和前端的鉴权/state 失去同步。所以前端在用户点「播放」
// 时把已加载的 movie 详情拍扁成下面这些 struct 一起 invoke 过来，
// Rust 只负责显示——不主动拉数据。
//
// `serde(rename_all = "camelCase")` 是因为 Tauri/serde 默认期待
// snake_case，但前端是 camelCase 的 TS 对象。

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MovieMeta {
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub original_title: Option<String>,
    #[serde(default)]
    pub year: Option<i32>,
    #[serde(default)]
    pub overview: Option<String>,
    #[serde(default, alias = "resources")]
    pub resources: Vec<ResourceMeta>,
    /// 后端 groups.seasons 的精简版：用来渲染顶部 「第 1 季 / 第 2 季」 tab
    /// 行 + 用 resource_ids 过滤集数。空就当单季处理。
    #[serde(default)]
    pub seasons: Vec<SeasonMeta>,
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SeasonMeta {
    pub season: i32,
    #[serde(default)]
    pub display_title: String,
    #[serde(default)]
    pub resource_ids: Vec<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourceMeta {
    pub id: String,
    /// 直接可播放的 stream URL（前端已经走过 getStreamUrl 转换）。
    /// 切源时 Rust 直接用它 loadfile，不需要再问前端。
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub display_label: Option<String>,
    #[serde(default)]
    pub quality_label: Option<String>,
    #[serde(default)]
    pub size_bytes: Option<u64>,
    /// 存储后端名称（"bilibili" / "115 网盘"），渲染成显眼填色 badge —
    /// 与 web Player.tsx 1931-1933 行的 storage_source.name chip 一致。
    #[serde(default)]
    pub storage_source: Option<String>,
    /// Episode number when the resource is part of a season; `None` for
    /// movies and one-off content. The webview computes this from
    /// `resource_info.display.episode` etc — we just consume the result.
    #[serde(default)]
    pub episode: Option<String>,
    /// Season number when applicable (1-indexed). `None` for standalone
    /// movies.
    #[serde(default)]
    pub season: Option<i32>,
    /// Pre-flattened technical badges (resolution / codec / HDR / Atmos
    /// / source) so the panel doesn't need to walk into media_info.
    #[serde(default)]
    pub badges: Vec<String>,
    /// Subtitles attached to this resource. Pre-resolved to absolute URLs
    /// by the webview (via `resolveAssetUrl`); Rust just feeds the URL to
    /// `mpv sub-add` when the user picks one. Empty vec is fine — the
    /// subtitle dropdown will still offer "关闭字幕" plus any internal
    /// tracks mpv discovers from the container.
    #[serde(default)]
    pub subtitles: Vec<SubtitleMeta>,
    /// 云端转码画质档位（仅 quarktv / uctv 资源命中）。前端拉过
    /// streaming-qualities 后把 available 档位拍扁送来，每档一个绝对
    /// stream-transcoded URL。空 = 不是云转码资源，HUD 不画清晰度菜单。
    #[serde(default)]
    pub qualities: Vec<QualityMeta>,
}

/// 一档云端转码画质。对应前端 NativeQualityMeta / 后端
/// streaming-qualities items[]。切档时 Rust 直接用 url loadfile，
/// 保留当前播放进度（区别于换集的从头播放）。
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QualityMeta {
    /// low / normal / high / super / 2k / 4k
    pub resolution: String,
    /// 展示名（LD / HD / FHD / 4K 等）；缺省时 UI 退到 resolution。
    #[serde(default)]
    pub label: Option<String>,
    /// 该档位的绝对播放 URL（前端已拼好 apiBase origin）。
    pub url: String,
    /// 是否后端默认档位，启动时优先选它起播。
    #[serde(default)]
    pub is_default: bool,
}

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SubtitleMeta {
    pub id: String,
    pub url: String,
    #[serde(default)]
    pub label: Option<String>,
    /// 后端 1.21+ 新增：来源 release 标题（去扩展名），比 label/filename 更可读。
    /// UI 展示优先用 display_name，缺失再退到 label / format / id。
    #[serde(default)]
    pub display_name: Option<String>,
    /// File extension hint ("srt" / "ass" / "vtt" ...). Optional — mpv
    /// sniffs the format itself, this is just for the dropdown label.
    #[serde(default)]
    pub format: Option<String>,
    #[serde(default)]
    pub is_default: bool,
}
