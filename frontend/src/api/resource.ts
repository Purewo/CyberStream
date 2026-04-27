import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const resourceService = {
  updateMetadata: async (id: string, metadata: any): Promise<any | null> => {
    return await fetchApi<any>(`/v1/resources/${id}/metadata`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata)
    });
  },
  
  getSubtitles: async (id: string): Promise<any[]> => {
    const data = await fetchApi<any[]>(`/v1/resources/${id}/subtitles`);
    return data || [];
  }
};

