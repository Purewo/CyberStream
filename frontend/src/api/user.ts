import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const userService = {
  getHistory: async (): Promise<HistoryItem[]> => {
    try {
      const data = await fetchApi<any>('/v1/user/history');
      if (!data) return [];

      let items: any[] = [];
      // API might return array directly OR { items: [...] } OR { data: [...] }
      if (Array.isArray(data)) {
          items = data;
      } else if (typeof data === 'object') {
          if (Array.isArray(data.items)) items = data.items;
          else if (Array.isArray(data.data)) items = data.data;
          else if (data.data && Array.isArray(data.data.items)) items = data.data.items;
      }

      return items.map(item => {
        const movieInfo = item.movie || item; 
        const movie = mapApiMovieToUi(movieInfo);
        
        const updatedAt = item.updated_at || item.created_at || new Date().toISOString();
        let dateObj = new Date(updatedAt);
        if (isNaN(dateObj.getTime())) dateObj = new Date();
        
        // Spec 1.16.0-beta uses position_sec and total_duration
        const progress = Number(item.position_sec || item.progress || 0);
        const duration = Number(item.total_duration || item.duration || movie.duration || 0);

        // Find matched season_card for history item
        const targetSeason = item.season || movie.target_season;
        if (targetSeason !== undefined && movie.season_cards) {
            const sc = movie.season_cards.find(c => c.season === targetSeason);
            if (sc) {
                if (sc.poster_url && sc.has_distinct_poster) {
                    movie.poster_url = sc.poster_url;
                    movie.cover_url = sc.poster_url;
                }
                if (sc.overview) {
                    movie.overview = sc.overview;
                    movie.desc = sc.overview;
                }
            }
        }

        return {
          ...movie,
          target_season: targetSeason,
          user_data: { ...(movie.user_data || {}), season: item.season || movie.user_data?.season, episode: item.episode || movie.user_data?.episode, episode_label: item.episode_label || movie.user_data?.episode_label },
          resourceId: item.resource_id, 
          progress: progress,
          duration: duration, 
          time_str: dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          date: dateObj.toLocaleDateString(),
          updated_at: updatedAt
        };
      }).sort((a, b) => new Date(b.updated_at!).getTime() - new Date(a.updated_at!).getTime());
    } catch (e) {
      console.warn("History API currently unstable or in 'failed_verification' mode", e);
      return [];
    }
  },

  clearHistory: async (): Promise<void> => {
    try {
      await fetch(`${API_BASE}/v1/user/history`, { method: 'DELETE' });
    } catch (e) { console.error(e); }
  },

  deleteHistoryItem: async (resourceId: string): Promise<void> => {
    try {
      await fetch(`${API_BASE}/v1/user/history/${resourceId}`, { method: 'DELETE' });
    } catch (e) { console.error(e); }
  },

  reportHistory: async (resourceId: string, positionSec: number, totalDuration: number, sessionId?: string) => {
    try {
      await fetch(`${API_BASE}/v1/user/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resource_id: resourceId,
          position_sec: Math.floor(positionSec),
          total_duration: Math.floor(totalDuration),
          device_id: getDeviceId(),
          device_name: navigator.userAgent,
          ...(sessionId ? { session_id: sessionId } : {})
        })
      });
    } catch (e) { console.error(e); }
  },

  getVault: async (): Promise<Movie[]> => {
    // Not in OpenAPI, return empty or mock
    return [];
  },

  toggleFavorite: async (movie: Movie) => {
    // Not in OpenAPI
    console.warn("Vault API not available in current spec");
  }
};

