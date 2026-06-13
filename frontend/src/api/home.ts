import { getApiBase } from '../platform';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries, HomepageConfig, HomepageSectionConfig } from '../types/index';

export const homeService = {
  getHomepage: async (): Promise<{ hero: any, sections: any[] } | null> => {
    const data = await fetchApi<{ hero: any, sections: any[] }>('/v1/homepage');
    return data || null;
  },
  getHomepageConfig: async (): Promise<HomepageConfig | null> => {
    return await fetchApi<HomepageConfig>('/v1/homepage/config');
  },
  updateHomepageConfig: async (
    patch: { hero_movie_id?: string | null; sections?: HomepageSectionConfig[] }
  ): Promise<HomepageConfig | null> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/homepage/config`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (!res.ok) return null;
      const json = await res.json().catch(() => null);
      // 后端 envelope: { code, msg, data: HomepageConfig }
      return (json && (json.data || json)) as HomepageConfig;
    } catch {
      return null;
    }
  },
};

