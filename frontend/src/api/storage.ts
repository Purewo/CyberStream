import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const storageService = {
  getProviderTypes: async (): Promise<any[]> => {
    // Falls back to empty array if not found, note that capabilities wraps data in .data if not unwrapped
    const data = await fetchApi<any>('/v1/storage/capabilities');
    return data?.items || [];
  },

  getSources: async (): Promise<import('../types/index').StorageSource[]> => {
    const data = await fetchApi<import('../types/index').StorageSource[]>('/v1/storage/sources');
    return data || [];
  },

  getSource: async (id: number): Promise<import('../types/index').StorageSource | null> => {
    return await fetchApi<import('../types/index').StorageSource>(`/v1/storage/sources/${id}`);
  },

  getSourceBrowse: async (id: number, browsePath: string = '/'): Promise<{ items: import('../types/index').FileItem[] | null, error?: string }> => {
    try {
      const res = await fetch(`${API_BASE}/v1/storage/sources/${id}/browse?path=${encodeURIComponent(browsePath)}&dirs_only=true`);
      const data = await res.json().catch(() => null);
      if (res.ok && data?.code === 200) {
        return { items: data.data?.items || [] };
      }
      return { items: null, error: data?.msg || `HTTP Error ${res.status}` };
    } catch (e: any) {
      return { items: null, error: e.message };
    }
  },

  checkHealth: async (id: number): Promise<import('../types/index').StorageSourceHealth | null> => {
    const data = await fetchApi<import('../types/index').StorageSource>(`/v1/storage/sources/${id}/health`);
    return data?.health || null;
  },

  addSource: async (name: string, type: string, config: any): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/storage/sources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, type, config })
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  updateSource: async (id: number, name: string, type: string, config: any): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/storage/sources/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, type, config })
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  deleteSource: async (id: number, keepMetadata: boolean = false): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/storage/sources/${id}?keep_metadata=${keepMetadata}`, {
        method: 'DELETE'
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  previewStorage: async (type: string, config: any, targetPath: string = '/'): Promise<{ items: import('../types/index').FileItem[] | null, error?: string }> => {
    try {
      const res = await fetch(`${API_BASE}/v1/storage/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, config, target_path: targetPath })
      });
      const data = await res.json().catch(() => null);
      
      if (res.ok && data?.code === 200) {
         return { items: data.data?.items || [] };
      }
      
      return { 
        items: null, 
        error: data?.msg || `HTTP Error ${res.status}` 
      };
    } catch (e: any) {
      return { items: null, error: e.message };
    }
  },

  scanSource: async (id: number, targetPath?: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/storage/sources/${id}/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(targetPath ? { target_path: targetPath } : {})
      });
      return res.ok;
    } catch {
      return false;
    }
  }
};

