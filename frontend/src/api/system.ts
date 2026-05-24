import { getApiBase } from '../platform';
import { fetchApi, fetchApiRaw, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';
import type { components } from './schema';

type BackgroundJobListResponse = components["schemas"]["BackgroundJobListResponse"];
type BackgroundJobResponse = components["schemas"]["BackgroundJobResponse"];
type BackgroundJobPruneResponse = components["schemas"]["BackgroundJobPruneResponse"];

/**
 * TMDB 配置 GET 返回的形状。出于安全考虑后端永远不回明文 token，
 * 只回 token_set:bool 让前端判定"已配置"。
 */
export interface TmdbConfig {
  token_set: boolean;
  proxy_enabled: boolean;
  proxy_url: string;
}

/**
 * PUT 提交时的 patch payload。三个字段都可选；只传部分字段即只更新那部分。
 * - token: 空字符串或 null = 清空；undefined = 保留不动
 * - proxy_enabled: bool
 * - proxy_url: 必须 http(s)/socks5:// 开头
 */
export interface TmdbConfigPatch {
  token?: string | null;
  proxy_enabled?: boolean;
  proxy_url?: string | null;
}

export const systemService = {
  getNotifications: async (): Promise<Notification[]> => {
    // Not in OpenAPI, return empty
    return [];
  },

  getScanStatus: async (): Promise<any | null> => {
    return await fetchApi<any>('/v1/scan');
  },

  // 全库扫描入口：扫描所有 StorageSource。后端契约仍有效，与
  // POST /v1/storage/sources/{id}/scan 共用扫描锁，扫描中返回 429。
  // 当前 UI 未启用此入口（业务优先用指定挂载源扫描），保留供维护用。
  triggerScan: async (type: 'full' | 'incremental' = 'incremental', targetPath?: string): Promise<boolean> => {
    try {
      const body: any = { type };
      if (targetPath) body.target_path = targetPath;
      
      const res = await fetch(`${getApiBase()}/v1/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      return res.ok || res.status === 202;
    } catch {
      return false;
    }
  },

  getReviewResources: async (page: number = 1, pageSize: number = 20, sourceId?: number, provider?: string): Promise<import('../types/index').ReviewResourceListResponse | null> => {
    let url = `/v1/reviews/resources?page=${page}&page_size=${pageSize}`;
    if (sourceId) url += `&source_id=${sourceId}`;
    if (provider) url += `&provider=${provider}`;
    const data = await fetchApi<import('../types/index').ReviewResourceListResponse>(url);
    if (data && 'data' in data && (data as any).data) { // Unpack if wrapped in data
       return (data as any).data; 
    }
    return data || null;
  },

  getJobs: async (type?: string, limit: number = 20): Promise<BackgroundJobListResponse | null> => {
    let url = `/v1/jobs?limit=${limit}`;
    if (type) url += `&type=${type}`;
    return await fetchApi<BackgroundJobListResponse>(url);
  },

  getJob: async (jobId: string): Promise<BackgroundJobResponse | null> => {
    return await fetchApi<BackgroundJobResponse>(`/v1/jobs/${jobId}`);
  },

  pruneJobs: async (keepDays?: number, dryRun?: boolean): Promise<BackgroundJobPruneResponse | null> => {
    const body: any = {};
    if (keepDays !== undefined) body.keep_days = keepDays;
    if (dryRun !== undefined) body.dry_run = dryRun;
    return await fetchApi<BackgroundJobPruneResponse>('/v1/jobs/prune', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  },

  // 后端 OpenAPI 文档索引；返回里包含后端运行版本（version / openapi_version），
  // 用作"关于"页里检查后端版本是否与前端同步。
  getDocsInfo: async (): Promise<{ version: string; openapi_version: string } | null> => {
    return await fetchApi<{ version: string; openapi_version: string }>('/v1/docs');
  },

  // ─── TMDB 配置 ───
  // 桌面单机分发场景：用户没法手改 NAS 的 .env.local，必须在 UI 里配。
  // 后端把这套配置直接写到 LOCALAPPDATA / 仓库根的 .env.local 里，下一次
  // 扫描立刻生效（current_app.config 也会同步刷一遍，热更新）。

  getTmdbConfig: async (): Promise<TmdbConfig | null> => {
    return await fetchApi<TmdbConfig>('/v1/system/tmdb-config');
  },

  setTmdbConfig: async (patch: TmdbConfigPatch): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/system/tmdb-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}` };
  }
};
