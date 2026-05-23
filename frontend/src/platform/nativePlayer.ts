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
