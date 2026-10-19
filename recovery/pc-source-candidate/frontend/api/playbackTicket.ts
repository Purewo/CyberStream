// 播放临时票据（playback ticket）。
//
// 代托管（用户管理）模式下后端 /stream 等播放端点强制要登录态（HttpOnly
// session cookie）。但 PC 端的 mpv / 外部播放器是独立进程，拿不到 WebView 的
// cookie，裸奔请求会 401。后端为此提供了「换票」端点：登录态换一张短期票据，
// 票据作为 query 参数 ?ticket=... 即可通过播放端点认证。
//
// 契约（后端已部署到 40161/40162）：
//   POST /api/v1/auth/playback-ticket  （需登录态，WebView fetch 带 cookie）
//   → { ticket, expires_at(unix秒), ttl(秒，默认 43200=12h) }
//   票据绑 user_id + session_version，不绑单个 resource，换集/切资源复用。
//   非法/过期访问播放端点 → HTTP 401 + 业务码 40130。
//
// 覆盖的播放端点（mpv / 外部进程直接发起的请求才需要拼票；前端 fetchApi 走
// cookie 的请求不需要）：
//   /resources/{id}/stream            （主视频流）
//   /resources/{id}/stream?subtitle_id=...（外挂字幕下载）
//   /resources/{id}/stream-transcoded （清晰度转码档）
//   /resources/{id}/streaming-qualities
//   /resources/{id}/audio-transcode
//
// 仅 PC 用。Web 端在浏览器里，<video>/fetch 自动带 cookie，不经过这里。

import { fetchApi } from './core';

interface PlaybackTicketDto {
  ticket: string;
  expires_at: number; // unix 秒
  ttl: number;        // 秒
}

interface CachedTicket {
  ticket: string;
  // 本地过期时刻（unix 毫秒）。比后端 expires_at 提前 5 分钟，留足正在播放
  // 的请求用，避免边界处刚拿就过期。
  expiresAtMs: number;
}

let cached: CachedTicket | null = null;
// 并发去重：多条资源 URL 同时要票时只发一次换票请求。
let inflight: Promise<string | null> | null = null;

const SAFETY_MARGIN_MS = 5 * 60 * 1000; // 提前 5 分钟视为过期

function isFresh(c: CachedTicket | null): c is CachedTicket {
  return !!c && Date.now() < c.expiresAtMs;
}

async function requestTicket(): Promise<string | null> {
  const data = await fetchApi<PlaybackTicketDto>('/v1/auth/playback-ticket', {
    method: 'POST',
  });
  if (!data?.ticket) return null;
  // 优先用后端 expires_at；缺失时退到 ttl；再退到默认 12h。
  const nowMs = Date.now();
  const expMs = data.expires_at
    ? data.expires_at * 1000
    : nowMs + (data.ttl ? data.ttl * 1000 : 43200_000);
  cached = {
    ticket: data.ticket,
    expiresAtMs: expMs - SAFETY_MARGIN_MS,
  };
  return cached.ticket;
}

/**
 * 拿一张有效票据。缓存未过期就复用；否则换新。换票失败返回 null（调用方
 * 应降级到不带票的 URL —— 在非用户管理后端上仍可播，用户管理后端会 401，
 * 但那种情况本就要登录）。并发调用共享同一次 inflight 请求。
 */
export async function ensureTicket(): Promise<string | null> {
  if (isFresh(cached)) return cached.ticket;
  if (inflight) return inflight;
  inflight = requestTicket().finally(() => {
    inflight = null;
  });
  return inflight;
}

/**
 * 作废当前缓存票据。收到后端 40130（票据过期/非法）时调用，下次 ensureTicket
 * 会重新换票。
 */
export function invalidateTicket(): void {
  cached = null;
}

/**
 * 给一个播放 URL 拼上 ticket query。无票（未登录 / 换票失败）时原样返回。
 * 已带 ticket 的 URL 不重复拼。
 */
export function appendTicket(url: string, ticket: string | null): string {
  if (!ticket || !url) return url;
  if (/[?&]ticket=/.test(url)) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}ticket=${encodeURIComponent(ticket)}`;
}

