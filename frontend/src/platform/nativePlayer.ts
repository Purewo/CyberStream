// CyberStream PC · native player launcher.
//
// On PC, the player page is NOT a React component — it's a separate
// Win32 window owned by Rust (libmpv + egui HUD; see
// pc/src-tauri/src/native_player/). The webview hands control over by
// calling this function with a fully resolved URL + auth headers + a
// resume position; Rust takes it from there.
//
// The promise resolves when the native window has been closed by the
// user (Esc / "返回" / video ended). Callers should use that as the
// cue to refresh history and put the webview focus back on the detail
// page.

import { invoke } from '@tauri-apps/api/core';

// ─── 百度网盘 stream UA 改写 ───
//
// 百度网盘 stream URL 经过几层 302 后落到 d.pcs.baidu.com 直链；这条直链
// 对请求方 UA 敏感，普通浏览器/播放器 UA 上去会被反爬挡掉。AList 的
// baidu_netdisk driver 默认 UA 就是下面这串，社区验证可用。
//
// 触发条件：playback.external_player.requires_user_agent_rewrite === true
// 或 playback.external_player.reason === 'baidunetdisk_requires_user_agent_rewrite'
// （后端 schema 里 requires_local_backend / reason 都标记了）。
//
// 后端目前不暴露具体 UA 字符串；这里集中一份常量，将来后端把 UA 放进
// manifest（比如 `external_player.user_agent`）后改一处即可。
const BAIDU_NETDISK_USER_AGENT = 'netdisk;P2SP;3.0.7.10;netdisk;';

/**
 * 后端返回的 playback.external_player 里需要 UA 改写的标记。
 * 调用方拿到 resource detail 后，把 external_player 段切下来传进来判断。
 */
export interface PlaybackHandoffHint {
  requires_user_agent_rewrite?: boolean;
  reason?: string | null;
}

/**
 * 当前资源是否要走 UA 改写。先看显式 boolean，再回退看 reason 里有没有
 * `_requires_user_agent_rewrite` 后缀（后端可能加新 storage_type 用相同
 * reason 模式）。两个都 false 时返回 false。
 */
export function needsUserAgentRewrite(hint?: PlaybackHandoffHint | null): boolean {
  if (!hint) return false;
  if (hint.requires_user_agent_rewrite === true) return true;
  if (typeof hint.reason === 'string' && /requires_user_agent_rewrite$/i.test(hint.reason)) {
    return true;
  }
  return false;
}

/** 选要改写成什么 UA。reason 给百度时用百度专用 UA；其他情况返回 null（不改）。 */
export function pickUserAgentForRewrite(hint?: PlaybackHandoffHint | null): string | null {
  if (!needsUserAgentRewrite(hint)) return null;
  // 目前仅百度网盘命中 UA 改写场景；其他 storage_type 将来若需要其他 UA，
  // 在这里按 reason 分支扩展。
  if (typeof hint?.reason === 'string' && /baidunetdisk/i.test(hint.reason)) {
    return BAIDU_NETDISK_USER_AGENT;
  }
  // 没标 reason 但 requires_user_agent_rewrite=true 的 fallback：仍用百度默认。
  return BAIDU_NETDISK_USER_AGENT;
}

/** 取 PC 本地媒体代理 base URL（http://127.0.0.1:<port>）。lib.rs 启动时
 *  绑定随机端口；前端外播前调一次拿到 base，用它把 stream URL 包成
 *  `<base>/stream?u=<encoded>&ua=<encoded>` 喂给 PotPlayer/VLC。
 *  代理未启动时返回 null（外播降级走原始 URL）。*/
export async function getMediaProxyBase(): Promise<string | null> {
  try {
    const base = await invoke<string | null>('media_proxy_url');
    return base || null;
  } catch {
    return null;
  }
}

/** 用本地代理把 stream URL 包成播放器可消费的 URL。base 为 null 时返回
 *  原 URL（降级——百度网盘外播会 403，但其他云盘正常）。*/
export function wrapWithMediaProxy(streamUrl: string, ua: string, proxyBase: string | null): string {
  if (!proxyBase) return streamUrl;
  const u = encodeURIComponent(streamUrl);
  const a = encodeURIComponent(ua);
  return `${proxyBase}/stream?u=${u}&ua=${a}`;
}

/**
 * Resource metadata as expected by the Rust right-side panel. Mirrors
 * `ResourceMeta` in `pc/src-tauri/src/native_player/meta.rs`.
 *
 * Fields are camelCase because Rust's serde is configured with
 * `rename_all = "camelCase"` for cross-boundary structs.
 */
export interface NativeResourceMeta {
  id: string;
  /** Direct stream URL — what mpv loadfile will use when this row is clicked. */
  url: string;
  filename?: string;
  displayLabel?: string;
  qualityLabel?: string;
  sizeBytes?: number;
  /** Storage backend name (e.g. "bilibili", "115 网盘") — rendered as a
   *  bright filled chip ahead of the title, mirroring the web Player. */
  storageSource?: string;
  /** Episode label ("1", "12", "Special 1") — surfaces in the panel grid. */
  episode?: string;
  /** Season number; null for standalone movies. */
  season?: number;
  /** Pre-flattened tech badges ("4K", "HEVC", "DV", "Atmos") — Rust just
   *  prints them as little chips next to the row title. */
  badges?: string[];
  /** Subtitles known to be attached to this resource at launch time.
   *  Each entry has an absolute URL Rust can hand straight to mpv via
   *  `sub-add`. Internal/embedded subtitles are NOT in this list — mpv
   *  discovers those itself when the container is loaded. */
  subtitles?: NativeSubtitleMeta[];
  /** 云端转码画质档位（仅 quarktv / uctv 资源命中）。后端把云盘原始下载链
   *  转码成多档分辨率；每档一个绝对 stream-transcoded URL，mpv loadfile 可直接
   *  消费。空 / 缺省 = 不是云转码资源，HUD 不画清晰度菜单，走原始 url 字段。*/
  qualities?: NativeQualityMeta[];
}

export interface NativeQualityMeta {
  /** low / normal / high / super / 2k / 4k */
  resolution: string;
  /** 后端给的展示名（LD / HD / FHD / 4K 等）；缺省时 HUD 退到 resolution。 */
  label?: string;
  /** 该档位的绝对播放 URL（getTranscodedStreamUrl 已拼好 apiBase origin）。 */
  url: string;
  /** 是否后端默认档位（default_resolution）；启动时优先选它起播。 */
  isDefault?: boolean;
}

export interface NativeSubtitleMeta {
  id: string;
  /** Absolute URL — webview already piped through resolveAssetUrl. */
  url: string;
  label?: string;
  /** Backend 1.21+ release-style display name (no extension). When present,
   *  Rust prefers this over `label` because it reads more naturally
   *  (release title vs. "Chinese Simplified + English ASS"). */
  displayName?: string;
  /** Format hint ("srt"/"ass"/"vtt" …). Optional, mpv will sniff. */
  format?: string;
  isDefault?: boolean;
}

export interface NativeMovieMeta {
  id: string;
  title: string;
  originalTitle?: string;
  year?: number;
  overview?: string;
  resources: NativeResourceMeta[];
  /**
   * Season groupings for shows with multi-season content. Each entry pairs a
   * season number with the resource ids that belong to it; the Rust panel
   * uses this to render a 「第 1 季 / 第 2 季」 tab strip and to filter the
   * episode grid down to the active season. Empty / omitted for movies and
   * single-season shows — Rust falls back to a flat list in that case.
   */
  seasons?: NativeSeasonMeta[];
}

export interface NativeSeasonMeta {
  season: number;
  /** Pre-formatted display label, e.g. "第 1 季" or "Season 2 · 剧场版". */
  displayTitle: string;
  /** Resource ids of the episodes in this season. */
  resourceIds: string[];
}

export interface NativePlayerOptions {
  url: string;
  /** Resume position in seconds. Use 0 to start from the beginning. */
  startTime?: number;
  /**
   * HTTP headers mpv should send when fetching the URL — typically
   * Authorization (and Cookie when the upstream uses session cookies).
   * Pairs of [name, value]; mpv joins them with `\r\n` internally.
   */
  headers?: Array<[string, string]>;
  /** Movie metadata for the right-side details panel; see NativeMovieMeta. */
  movie?: NativeMovieMeta;
  /** Which resource is currently playing (used to highlight the row). */
  currentResourceId?: string;
  /** Same value as the webview's `cyber_device_id` localStorage entry —
   *  the backend `/v1/user/history` endpoint identifies users by this
   *  rather than by an Authorization header (see user.ts). */
  deviceId: string;
  /** Backend root WITHOUT the trailing `/api` (Rust path-joins `/api/v1/...`
   *  on top). Pass the same origin the webview is hitting. */
  apiBase: string;
  /** Session id for this playback session. Optional — Rust generates one
   *  if omitted. Format: `pc-<uuid>` so backend logs distinguish PC sessions
   *  from web sessions. */
  sessionId?: string;
}

export async function launchNativePlayer(opts: NativePlayerOptions): Promise<void> {
  await invoke('open_pc_player', {
    options: {
      url: opts.url,
      startTime: opts.startTime ?? 0,
      headers: opts.headers ?? [],
      movie: opts.movie ?? null,
      currentResourceId: opts.currentResourceId ?? null,
      deviceId: opts.deviceId,
      apiBase: opts.apiBase,
      sessionId: opts.sessionId ?? null,
    },
  });
  // 桌面入侵：用过一次 PC 原生播放器即解锁（成就后端幂等，重复无副作用）
  import('../api/user').then((m) =>
    m.unlockBehaviorAchievement('desktop_invasion', { silent: false }),
  ).catch(() => {});
}

// ─────────────────────── 外部播放器拉起 ───────────────────────

export interface ExternalPlayerLaunchOptions {
  /** "potplayer" | "vlc"。其他值（IINA、nPlayer、MX、Infuse 等）现阶段没接 */
  player: 'potplayer' | 'vlc';
  streamUrl: string;
  /** 默认绑定字幕 URL（绝对地址）。可空。 */
  subtitleUrl?: string;
  /** 起始秒数（resume）。可空。 */
  startTime?: number;
}

export interface ExternalPlayerLaunchResult {
  launched: boolean;
  /** "exe" = 直接启动了本地可执行文件；"fallback_required" = 没找到，前端走
   *  URL scheme 兜底；"url_scheme" = Rust 直接走了 scheme。 */
  method: 'exe' | 'fallback_required' | 'url_scheme';
  message?: string | null;
  exePath?: string | null;
}

/** 调用 Rust 端 launch_external_player 命令。失败时 throw —— 调用方 catch 后
 *  通常应退回到 shellOpen(URL_scheme) 兜底。 */
export async function launchExternalPlayerNative(
  opts: ExternalPlayerLaunchOptions,
): Promise<ExternalPlayerLaunchResult> {
  const result = await invoke<ExternalPlayerLaunchResult>('launch_external_player', {
    req: {
      player: opts.player,
      streamUrl: opts.streamUrl,
      subtitleUrl: opts.subtitleUrl ?? null,
      startTime: opts.startTime ?? null,
    },
  });
  // 影院模式：用过一次外部播放器即解锁。即使 fallback_required 用户后面也会
  // 走 URL scheme 兜底，但 cinema_mode 的语义是「调用过」，这里成功 invoke
  // 就算数（fallback 路径是 shellOpen，不经这里，所以那条路另算）
  if (result.launched) {
    import('../api/user').then((m) =>
      m.unlockBehaviorAchievement('cinema_mode', { silent: false }),
    ).catch(() => {});
  }
  return result;
}
