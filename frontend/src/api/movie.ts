import { getApiBase } from '../platform';
import { fetchApi, fetchApiRaw, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse, ApiMovieList } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';
import type { components } from './schema';

type MetadataProviderCatalog = components["schemas"]["MetadataProviderCatalog"];
type MovieMetadataSearchResponseData = components["schemas"]["MovieMetadataSearchResponseData"];
type MovieMetadataMatchPreviewData = components["schemas"]["MovieMetadataMatchPreviewData"];
type MovieMetadataMatchRequest = components["schemas"]["MovieMetadataMatchRequest"];


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
    metadata_issue_code?: string,
    source_id?: number
  } = {}): Promise<{ items: Movie[], meta?: ApiPagination }> => {
    const { genre, sort_by, order, country, year, needs_attention, metadata_review_priority, metadata_issue_code, source_id } = filters;
    let url = `/v1/movies?page=${page}&page_size=${limit}`;
    if (genre && genre !== '全部类型') url += `&genre=${encodeURIComponent(genre)}`;
    if (sort_by) url += `&sort_by=${encodeURIComponent(sort_by)}`;
    if (order) url += `&order=${encodeURIComponent(order)}`;
    if (country && country !== '全部地区') url += `&country=${encodeURIComponent(country)}`;
    if (year && year !== '全部年份') url += `&year=${encodeURIComponent(year)}`;
    if (needs_attention !== undefined) url += `&needs_attention=${needs_attention}`;
    if (metadata_review_priority) url += `&metadata_review_priority=${metadata_review_priority}`;
    if (metadata_issue_code) url += `&metadata_issue_code=${metadata_issue_code}`;
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
    return `${getApiBase()}/v1/resources/${resourceId}/stream`;
  },
  
  getSubtitleUrl: (resourceId: string, subtitle: any): string => {
    if (typeof subtitle === 'string') {
        return `${getApiBase()}/v1/resources/${resourceId}/stream?subtitle_id=${subtitle}`;
    }
    if (subtitle?.web_player?.url) {
        return subtitle.web_player.url.replace(/^\/api/, getApiBase());
    }
    return `${getApiBase()}/v1/resources/${resourceId}/stream?subtitle_id=${subtitle?.id || subtitle}`;
  },

  searchOnlineSubtitles: async (resourceId: string, keyword?: string): Promise<any> => {
    let url = `/v1/resources/${resourceId}/subtitles/online/search`;
    if (keyword) {
      url += `?keyword=${encodeURIComponent(keyword)}`;
    }
    return await fetchApi<any>(url);
  },

  bindOnlineSubtitle: async (resourceId: string, candidateId: string, downloadIndex?: number): Promise<any> => {
    const payload: any = { candidate_id: candidateId, confirm: true };
    if (downloadIndex !== undefined) {
      payload.download_index = downloadIndex;
    }
    return await fetchApi<any>(`/v1/resources/${resourceId}/subtitles/online/bind`, {
      method: "POST",
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  },

  previewOnlineSubtitle: async (resourceId: string, candidateId: string, downloadIndex?: number): Promise<Blob | null> => {
    try {
      const payload: any = { candidate_id: candidateId };
      if (downloadIndex !== undefined) {
        payload.download_index = downloadIndex;
      }
      const res = await fetch(`${getApiBase()}/v1/resources/${resourceId}/subtitles/online/download`, {
        method: "POST",
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) return null;
      return await res.blob();
    } catch {
      return null;
    }
  },

  deleteSubtitle: async (resourceId: string, subtitleId: string): Promise<any> => {
    return await fetchApi<any>(`/v1/resources/${resourceId}/subtitles/${subtitleId}`, {
      method: "DELETE"
    });
  },

  setDefaultSubtitle: async (resourceId: string, subtitleId: string): Promise<any> => {
    return await fetchApi<any>(`/v1/resources/${resourceId}/subtitles/${subtitleId}/default`, {
      method: "POST"
    });
  },

  uploadSubtitle: async (resourceId: string, file: File, setDefault: boolean = false): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("set_default", String(setDefault));

    // For file upload, we need to omit the Content-Type header so the browser sets the boundary correctly
    const res = await fetch(`${getApiBase()}/v1/resources/${resourceId}/subtitles/upload`, {
      method: "POST",
      body: formData,
    });
    
    if (res.ok) {
      const data = await res.json();
      return data;
    } else {
      throw new Error('Upload failed');
    }
  },

  // 修改影片总影视库发布状态
  // API Endpoints for Image Cache
  getImageCacheStatus: async (id: string, kinds?: string): Promise<any> => {
    const queryId = movieService.getRealId(id);
    let url = `/v1/movies/${queryId}/images/status`;
    if (kinds) url += `?kinds=${kinds}`;
    return await fetchApi<any>(url);
  },

  clearImageCache: async (id: string, kind: 'poster' | 'backdrop'): Promise<any> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/images/${kind}`, {
      method: 'DELETE'
    });
  },

  preloadImages: async (movieIds?: string[], kinds?: string[], limit?: number, refresh?: boolean): Promise<any> => {
    const body: any = {};
    if (movieIds) body.movie_ids = movieIds;
    if (kinds) body.kinds = kinds;
    if (limit) body.limit = limit;
    if (refresh !== undefined) body.refresh = refresh;
    return await fetchApi<any>('/v1/images/preload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  },

  refreshImages: async (movieIds?: string[], kinds?: string[], limit?: number, options?: { purge?: boolean; clear_cache?: boolean; preload?: boolean; refresh?: boolean; }): Promise<any> => {
    const body: any = { ...options };
    if (movieIds) body.movie_ids = movieIds;
    if (kinds) body.kinds = kinds;
    if (limit) body.limit = limit;
    return await fetchApi<any>('/v1/images/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  },

  updateCatalogVisibility: async (id: string, status: 'auto' | 'published' | 'hidden', force?: boolean, note?: string): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const body: any = { status };
    if (force) body.force = force;
    if (note) body.note = note;
    
    const res = await fetch(`${getApiBase()}/v1/movies/${queryId}/catalog-visibility`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    
    if (res.status === 409) {
      const errorData = await res.json().catch(() => ({}));
      throw { status: 409, data: errorData };
    }
    
    if (!res.ok) {
      return null;
    }
    
    const json = await res.json();
    if (json.code !== 200) return null;
    
    return mapApiMovieToUi(json.data);
  },

  // 获取支持的元数据 Providers
  getMetadataProviders: async (): Promise<MetadataProviderCatalog | null> => {
    return await fetchApi<MetadataProviderCatalog>('/v1/metadata/providers');
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

  // 元数据候选预览（dry-run，默认不写库）。后端默认 apply=false，仅返回 preview/diff/warnings/apply_payload。
  previewMetadataMatch: async (id: string, candidate_id: string, provider: string, unlockedFields: string[] = [], mediaTypeHint?: 'movie' | 'tv'): Promise<MovieMetadataMatchPreviewData | null> => {
    const queryId = movieService.getRealId(id);
    const body: MovieMetadataMatchRequest = { candidate_id, provider, apply: false };
    if (!provider) body.tmdb_id = candidate_id;
    if (unlockedFields.length > 0) body.metadata_unlocked_fields = unlockedFields;
    if (mediaTypeHint) body.media_type_hint = mediaTypeHint;

    const data = await fetchApi<MovieMetadataMatchPreviewData>(`/v1/movies/${queryId}/metadata/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    return data;
  },

  // 应用元数据候选。优先使用后端 preview 返回的 apply_payload；后端会再次校验，缺海报时返回 409，需要 allow_missing_poster=true 才能强行写入。
  applyMetadataMatch: async (
    id: string,
    applyPayload: MovieMetadataMatchRequest,
    options: { allowMissingPoster?: boolean } = {}
  ): Promise<{ ok: true; movie: Movie } | { ok: false; status: number; code?: number; msg?: string }> => {
    const queryId = movieService.getRealId(id);
    const body: MovieMetadataMatchRequest = { ...applyPayload, apply: true };
    if (options.allowMissingPoster) body.allow_missing_poster = true;

    const result = await fetchApiRaw<ApiMovieDetailed>(`/v1/movies/${queryId}/metadata/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (result.ok && result.data) {
      return { ok: true, movie: mapApiMovieToUi(result.data) };
    }
    return { ok: false, status: result.status, code: result.code, msg: result.msg };
  },

  // 兼容旧接口：一步式匹配（直接 apply）。新代码请优先 previewMetadataMatch + applyMetadataMatch。
  matchMetadata: async (id: string, candidate_id: string, provider: string, unlockedFields: string[] = [], mediaTypeHint?: 'movie' | 'tv'): Promise<Movie | null> => {
    const queryId = movieService.getRealId(id);
    const body: MovieMetadataMatchRequest = { candidate_id, provider, apply: true };
    if (!provider) body.tmdb_id = candidate_id;
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
      const res = await fetch(`${getApiBase()}/v1/movies/${queryId}`, { method: 'DELETE' });
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
    if (filters?.metadata_issue_code) url += `&metadata_issue_code=${filters.metadata_issue_code}`;
    
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
  searchMetadataCandidates: async (id: string, query?: string, year?: number, providers?: string): Promise<MovieMetadataSearchResponseData | null> => {
    const queryId = movieService.getRealId(id);
    let url = `/v1/movies/${queryId}/metadata/search?limit=8`;
    if (query) url += `&query=${encodeURIComponent(query)}`;
    if (year) url += `&year=${year}`;
    if (providers) url += `&providers=${encodeURIComponent(providers)}`;
    
    return await fetchApi<MovieMetadataSearchResponseData>(url);
  },

  // 获取影片资源与季集分组
  getResources: async (id: string): Promise<import('../types/index').MovieResourceGroups | null> => {
    let queryId = String(id);
    if (queryId.includes('-S')) {
      queryId = queryId.split('-S')[0];
    }
    const resData = await fetchApi<import('../types/index').MovieResourceGroups>(`/v1/movies/${queryId}/resources`);
    if (resData) {
        if (resData.items) {
          resData.items = resData.items.filter(item => {
            const size = item.size_bytes !== undefined ? item.size_bytes : item.resource_info?.file?.size_bytes;
            if (size !== undefined && size < 1024 * 1024 * 5) return false;
            // Also explicitly hide exactly 0 bytes or 0GB as requested
            if (size === 0) return false;
            return true;
          });
        }
        if (resData.groups?.seasons) {
           resData.groups.seasons.forEach(season => {
               season.resource_ids = season.resource_ids.filter(id => resData.items?.some(i => i.id === id));
           });
           resData.groups.seasons = resData.groups.seasons.filter(season => season.resource_ids.length > 0);
        }
    }
    return resData;
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

  // === 🔵 [新增] Metadata and Diagnostics endpoints ===
  getReviewTaxonomy: async (): Promise<any | null> => {
    return await fetchApi<any>('/v1/metadata/review-taxonomy');
  },

  getMetadataQualitySummary: async (): Promise<any | null> => {
    return await fetchApi<any>('/v1/metadata/quality-summary');
  },

  getEpisodeReviewItems: async (page = 1, pageSize = 20, filters?: any): Promise<{items: any[], meta: any}> => {
    let url = `/v1/metadata/episode-review-items?page=${page}&page_size=${pageSize}`;
    if (filters?.library_id) url += `&library_id=${filters.library_id}`;
    if (filters?.metadata_issue_code) url += `&metadata_issue_code=${filters.metadata_issue_code}`;
    const data = await fetchApi<any>(url);
    if (!data) return { items: [], meta: null };
    return {
      items: data.items || [],
      meta: data.meta || data.pagination
    };
  },

  getEpisodeDiagnostics: async (id: string): Promise<any | null> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/episode-diagnostics`);
  },

  planBatchReScrapeMetadata: async (options: any): Promise<any | null> => {
    return await fetchApi<any>('/v1/metadata/re-scrape/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  },

  startBatchReScrapeMetadataJob: async (options: any): Promise<components["schemas"]["BackgroundJobResponse"] | null> => {
    return await fetchApi<any>('/v1/metadata/re-scrape/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
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
  },
  
  // 获取其他视频归档队列
  listOtherVideos: async (page = 1, pageSize = 20, filters?: any): Promise<{items: any[], meta: any}> => {
    let url = `/v1/other-videos?page=${page}&page_size=${pageSize}`;
    if (filters?.keyword) url += `&keyword=${encodeURIComponent(filters.keyword)}`;
    if (filters?.source_id) url += `&source_id=${filters.source_id}`;
    
    const data = await fetchApi<any>(url);
    if (!data) return { items: [], meta: null };
    return {
      items: data.items || [],
      meta: data.pagination || data.meta
    };
  },

  // 创建手工影视条目
  createManualMovie: async (options: any): Promise<Movie | null> => {
    const data = await fetchApi<ApiMovieDetailed>('/v1/movies/manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
    if (!data) return null;
    return mapApiMovieToUi(data);
  },

  // 挂载资源到手工条目
  attachResourceToMovie: async (id: string, options: any): Promise<any | null> => {
    const queryId = movieService.getRealId(id);
    return await fetchApi<any>(`/v1/movies/${queryId}/resources/attach`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  }
};

