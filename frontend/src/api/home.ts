import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const homeService = {
  getHomepage: async (): Promise<{ hero: any, sections: any[] } | null> => {
    const data = await fetchApi<{ hero: any, sections: any[] }>('/v1/homepage');
    return data || null;
  },
  getHomepageConfig: async (): Promise<any | null> => {
    return await fetchApi<any>('/v1/homepage/config');
  },
  updateHomepageConfig: async (config: any): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/homepage/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      return res.ok;
    } catch {
      return false;
    }
  }
};

