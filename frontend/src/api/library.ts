import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

import { movieService } from './movie';
export const libraryService = {
  getLibraries: async (): Promise<import('../types/index').Library[]> => {
    const data = await fetchApi<import('../types/index').Library[]>('/v1/libraries');
    return data || [];
  },
  
  createLibrary: async (name: string, slug: string, description?: string): Promise<number | null> => {
    try {
      const data = await fetchApi<{ id: number }>('/v1/libraries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, slug, description })
      });
      return data?.id || null;
    } catch {
      return null;
    }
  },

  updateLibrary: async (id: number, data: any): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  deleteLibrary: async (id: number): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${id}`, {
        method: 'DELETE'
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  getLibrarySources: async (id: number): Promise<import('../types/index').LibrarySourceBinding[]> => {
    const data = await fetchApi<import('../types/index').LibrarySourceBinding[]>(`/v1/libraries/${id}/sources`);
    return data || [];
  },

  bindLibrarySource: async (libraryId: number, sourceId: number, rootPath: string = '/'): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${libraryId}/sources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: sourceId, root_path: rootPath })
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  unbindLibrarySource: async (libraryId: number, bindingId: number): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${libraryId}/sources/${bindingId}`, {
        method: 'DELETE'
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  getFilteredMovies: async (libraryId: number, limit = 20, page = 1, genre?: string, sort_by?: string, order?: string, country?: string, year?: string): Promise<{ items: Movie[], meta?: ApiPagination }> => {
    let url = `/v1/libraries/${libraryId}/movies?page=${page}&page_size=${limit}`;
    if (genre && genre !== '全部类型') url += `&genre=${encodeURIComponent(genre)}`;
    if (country && country !== 'all' && country !== '全部地区') url += `&country=${encodeURIComponent(country)}`;
    if (year && year !== 'all' && year !== '全部年份') url += `&year=${encodeURIComponent(year)}`;
    if (sort_by) url += `&sort_by=${sort_by}`;
    if (order) url += `&order=${order}`;

    const data = await fetchApi<ApiMovieList>(url);
    if (!data) return { items: [] };

    return {
      items: movieService.flattenMovies(data.items),
      meta: data.pagination
    };
  },

  getFilters: async (libraryId: number): Promise<FilterDictionaries | null> => {
    const data = await fetchApi<FilterDictionaries>(`/v1/libraries/${libraryId}/filters`);
    return data || null;
  },

  getFeatured: async (libraryId: number): Promise<Movie[]> => {
    const data = await fetchApi<ApiMovieSimple[]>(`/v1/libraries/${libraryId}/featured`);
    if (!data) return [];
    return data.map(mapApiMovieToUi);
  },

  getRecommendations: async (libraryId: number): Promise<Movie[]> => {
    const data = await fetchApi<ApiMovieSimple[]>(`/v1/libraries/${libraryId}/recommendations`);
    if (!data) return [];
    return data.map(mapApiMovieToUi);
  },

  scanLibrary: async (libraryId: number): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${libraryId}/scan`, {
        method: 'POST'
      });
      return res.ok || res.status === 202;
    } catch {
      return false;
    }
  },

  getMovieMemberships: async (libraryId: number, page = 1, limit = 20, mode?: string): Promise<any> => {
    let url = `/v1/libraries/${libraryId}/movie-memberships?page=${page}&page_size=${limit}`;
    if (mode) url += `&mode=${mode}`;
    const data = await fetchApi<any>(url);
    if (!data) return { items: [], meta: null };
    return {
      items: (data.items || []).map((item: any) => ({
        ...item,
        movie: item.movie ? mapApiMovieToUi(item.movie) : null
      })),
      meta: data.pagination
    };
  },

  createMovieMembership: async (libraryId: number, mode: 'include' | 'exclude', movieIds: string[], sortOrder = 0): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${libraryId}/movie-memberships`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, movie_ids: movieIds, sort_order: sortOrder })
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  deleteMovieMemberships: async (libraryId: number, movieIds: string[]): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/v1/libraries/${libraryId}/movie-memberships/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movie_ids: movieIds })
      });
      return res.ok;
    } catch {
      return false;
    }
  }
};

