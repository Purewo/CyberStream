import { API_BASE } from '../constants/index';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const movieService = {
  // Helper to extract real ID from pseudo-IDs used in frontend lists
  getRealId: (id: string | number): string => {
    let queryId = String(id);
    if (queryId.includes('-S')) {
      queryId = queryId.split('-S')[0];
    }
    return queryId;
  },

  // Helper to map and flatten season cards if present
  flattenMovies: (apiMovies: ApiMovieSimple[]): Movie[] => {
    const result: Movie[] = [];
    for (const item of apiMovies) {
      if (item.has_multi_season_content && item.season_cards && item.season_cards.length > 0) {
        for (const sc of item.season_cards) {
          result.push(mapSeasonCardToUi(sc, item));
        }
      } else {
        result.push(mapApiMovieToUi(item));
      }
    }
    return result;
  },

  getAll: async (limit = 20, page = 1, filters: {
    genre?: string,
    sort_by?: string,
    order?: string,
    country?: string,
    year?: string,
    needs_attention?: boolean,
    metadata_review_priority?: string,
    source_id?: number
  } = {}): Promise<{ items: Movie[], meta?: ApiPagination }> => {
    const { genre, sort_by, order, country, year, needs_attention, metadata_review_priority, source_id } = filters;
    let url = `/v1/movies?page=${page}&page_size=${limit}`;
    if (genre && genre !== '全部类型') url += `&genre=${encodeURIComponent(genre)}`;
    if (sort_by) url += `&sort_by=${encodeURIComponent(sort_by)}`;
    if (order) url += `&order=${encodeURIComponent(order)}`;
    if (country && country !== '全部地区') url += `&country=${encodeURIComponent(country)}`;
    if (year && year !== '全部年份') url += `&year=${encodeURIComponent(year)}`;
    if (needs_attention !== undefined) url += `&needs_attention=${needs_attention}`;
    if (metadata_review_priority) url += `&metadata_review_priority=${metadata_review_priority}`;
    if (source_id) url += `&source_id=${source_id}`;
    
    const data = await fetchApi<{ items: ApiMovieSimple[], pagination: ApiPagination }>(url);
    if (!data) return { items: [] };
    
    return {
      items: movieService.flattenMovies(data.items),
      meta: data.pagination
    };
  },

  getGenres: async (): Promise<Genre[]> => {
    const data = await fetchApi<FilterDictionaries>('/v1/filters');
    return data?.genres || [];
  },
  
  getGlobalFilters: async (): Promise<FilterDictionaries | null> => {
    return await fetchApi<FilterDictionaries>('/v1/filters');
  },

  // Global getFeatured removed (legacy endpoint)
  getTop: async (type: string, limit = 15): Promise<Movie[]> => {
    // Note: use server-side sorting for accuracy
    const data = await fetchApi<ApiMovieList>(`/v1/movies?page_size=${limit}&sort_by=rating&order=desc`);
    if (!data) return [];
    return movieService.flattenMovies(data.items);
  },

  search: async (query: string): Promise<Movie[]> => {
    const data = await fetchApi<{ items: ApiMovieSimple[] }>(`/v1/movies?keyword=${encodeURIComponent(query)}&page_size=50`);
    if (!data) return [];
    return movieService.flattenMovies(data.items);
  },

  getDetail: async (id: string | number): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const data = await fetchApi<ApiMovieDetailed>(`/v1/movies/${queryId}`);
    console.log("getDetail api response data:", data);
    if (!data) return null;
    return mapApiMovieToUi(data);
  },

  getRecommendations: async (limit = 12, strategy: 'default' | 'latest' | 'top_rated' | 'surprise' | 'continue_watching' = 'default'): Promise<Movie[]> => {
    const data = await fetchApi<ApiMovieSimple[]>(`/v1/recommendations?limit=${limit}&strategy=${strategy}`);
    if (!data) return [];
    return movieService.flattenMovies(data);
  },
  
  getContextRecommendations: async (id: string, limit = 8, mediaTypeHint?: 'movie' | 'tv'): Promise<Movie[]> => {
    const queryId = movieService.getRealId(id);
    let url = `/v1/movies/${queryId}/recommendations?limit=${limit}`;
    if (mediaTypeHint) url += `&media_type_hint=${mediaTypeHint}`;
    const data = await fetchApi<ApiMovieSimple[]>(url);
    if (!data) return [];
    return movieService.flattenMovies(data);
  },
  
  getStreamUrl: (resourceId: string): string => {
    return `${API_BASE}/v1/resources/${resourceId}/stream`;
  },

  updateMetadata: async (id: string, metadata: any): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const data = await fetchApi<ApiMovieDetailed>(`/v1/movies/${queryId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata)
    });
    if (!data) return null;
    return mapApiMovieToUi(data);
  },

  matchMetadata: async (id: string, tmdb_id: string, unlockedFields: string[] = [], mediaTypeHint?: 'movie' | 'tv'): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const body: any = { tmdb_id };
    if (unlockedFields.length > 0) body.metadata_unlocked_fields = unlockedFields;
    if (mediaTypeHint) body.media_type_hint = mediaTypeHint;

    const data = await fetchApi<ApiMovieDetailed>(`/v1/movies/${queryId}/metadata/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!data) return null;
    return mapApiMovieToUi(data);
  },

  // 刷新影片元数据
  refreshMetadata: async (id: string, options?: { media_type_hint?: 'movie' | 'tv' }): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const data = await fetchApi<ApiMovieDetailed>(`/v1/movies/${queryId}/metadata/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options || {})
    });
    if (!data) return null;
    return mapApiMovieToUi(data);
  },

  // 重新刮削元数据 (Re-scrape)
  reScrapeMetadata: async (id: string, options: { 
    tmdb_id?: string, 
    media_type_hint?: 'movie' | 'tv', 
    allow_nfo?: boolean,
    force_refresh?: boolean
  } = {}): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const data = await fetchApi<ApiMovieDetailed>(`/v1/movies/${queryId}/metadata/re-scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
    if (!data) return null;
    return mapApiMovieToUi(data);
  },

  // 删除影片实体 (物理文件不会被删除，仅从数据库移除档案)
  delete: async (id: string | number): Promise<boolean> => {
    try {
      const queryId = movieService.getRealId(id);
      const res = await fetch(`${API_BASE}/v1/movies/${queryId}`, { method: 'DELETE' });
      return res.ok;
    } catch {
      return false;
    }
  },

  // 获取元数据工作台总览
  getMetadataOverview: async (): Promise<import('../types/index').MetadataOverview | null> => {
    return await fetchApi<import('../types/index').MetadataOverview>('/v1/metadata/overview');
  },

  // 获取工作台明细 (Work Items)
  getMetadataWorkItems: async (page = 1, pageSize = 20, filters?: any): Promise<{items: any[], meta: any}> => {
    let url = `/v1/metadata/work-items?page=${page}&page_size=${pageSize}`;
    if (filters?.keyword) url += `&keyword=${encodeURIComponent(filters.keyword)}`;
    if (filters?.metadata_source_group) url += `&metadata_source_group=${filters.metadata_source_group}`;
    if (filters?.metadata_review_priority) url += `&metadata_review_priority=${filters.metadata_review_priority}`;
    
    const data = await fetchApi<any>(url);
    if (!data) return { items: [], meta: null };
    return {
      items: (data.items || []).map((item: any) => ({
        ...item,
        movie: item.movie ? mapApiMovieToUi(item.movie) : null
      })),
      meta: data.meta
    };
  },

  // 批量定点重刮影片元数据
  batchReScrapeMetadata: async (movieIds: string[], options?: { allow_nfo?: boolean, force_refresh?: boolean }): Promise<any | null> => {
    return await fetchApi<any>('/v1/metadata/re-scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie_ids: movieIds, ...options })
    });
  },

  // 预览单条影片元数据管线结果
  previewMetadataPipeline: async (id: string, options?: { allow_nfo?: boolean }): Promise<any | null> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/metadata/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options || {})
    });
  },

  // 搜索影片元数据候选
  searchMetadataCandidates: async (id: string, query?: string, year?: number): Promise<any[]> => {
    const queryId = movieService.getRealId(id);
    let url = `/v1/movies/${queryId}/metadata/search?limit=8`;
    if (query) url += `&query=${encodeURIComponent(query)}`;
    if (year) url += `&year=${year}`;
    
    const res = await fetchApi<any>(url);
    if (!res) return [];
    return res.items || [];
  },

  // 获取影片资源与季集分组
  getResources: async (id: string): Promise<import('../types/index').MovieResourceGroups | null> => {
    let queryId = String(id);
    if (queryId.includes('-S')) {
      queryId = queryId.split('-S')[0];
    }
    return await fetchApi<import('../types/index').MovieResourceGroups>(`/v1/movies/${queryId}/resources`);
  },

  // 批量修改影片资源元数据
  updateResourcesMetadata: async (id: string, items: any[]): Promise<any | null> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/resources/metadata`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items })
    });
  },

  // 获取影片季列表
  getSeasons: async (id: string): Promise<any | null> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/seasons`);
  },

  // 修改单季元数据
  updateSeasonMetadata: async (id: string, season: number, metadata: any): Promise<any | null> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/seasons/${season}/metadata`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata)
    });
  }
};

