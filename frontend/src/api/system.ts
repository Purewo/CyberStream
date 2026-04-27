import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const systemService = {
  getNotifications: async (): Promise<Notification[]> => {
    // Not in OpenAPI, return empty
    return [];
  },

  getScanStatus: async (): Promise<import('../types/index').ScanStatus | null> => {
    const data = await fetchApi<import('../types/index').ScanStatus>('/v1/scan');
    return data || null;
  },

  triggerScan: async (type: 'full' | 'incremental' = 'incremental', targetPath?: string): Promise<boolean> => {
    try {
      const body: any = { type };
      if (targetPath) body.target_path = targetPath;
      
      const res = await fetch(`${API_BASE}/v1/scan`, {
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
  }
};