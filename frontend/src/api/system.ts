import { getApiBase } from '../platform';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';
import type { components } from './schema';

type BackgroundJobListResponse = components["schemas"]["BackgroundJobListResponse"];
type BackgroundJobResponse = components["schemas"]["BackgroundJobResponse"];
type BackgroundJobPruneResponse = components["schemas"]["BackgroundJobPruneResponse"];

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
  }
};
