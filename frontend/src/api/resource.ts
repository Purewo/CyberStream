import { getApiBase } from '../platform';
import { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries, StreamingQualitiesResponse } from '../types/index';
import type { components } from './schema';

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
  },

  getSubtitleSettings: async (id: string): Promise<any | null> => {
    return await fetchApi<any>(`/v1/resources/${id}/subtitle-settings`);
  },

  updateSubtitleSettings: async (id: string, settings: any): Promise<any | null> => {
    return await fetchApi<any>(`/v1/resources/${id}/subtitle-settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings })
    });
  },

  getExternalPlaybackInfo: async (id: string): Promise<any | null> => {
    return await fetchApi<any>(`/v1/resources/${id}/external-playback`);
  },

  getAudioTranscodeUrl: (id: string, start?: number, force_bitrate?: number): string => {
    let url = `${getApiBase()}/v1/resources/${id}/audio-transcode`;
    const params = new URLSearchParams();
    if (start !== undefined) params.append('start', String(start));
    if (force_bitrate !== undefined) params.append('force_bitrate', String(force_bitrate));
    const qs = params.toString();
    if (qs) url += `?${qs}`;
    return url;
  },

  stopAudioTranscode: async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/resources/${id}/audio-transcode`, {
        method: 'DELETE'
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  // ─── 云转码画质（QuarkTV / UCTV / Aliyundrive 等） ───
  //
  // 凡 playback.cloud_transcode.supported=true 的资源命中（后端按来源分发，
  // 不要按网盘名硬编码）。档位名因来源而异（夸克 low/normal/high/super/2k/4k，
  // 阿里 ld/sd/hd/fhd/qhd/4k），前端只遍历 items、不枚举档位名。
  // 详见 GET /v1/docs/frontend-managed-quark-uc / -aliyundrive。
  //
  // 返回值里 items[].available=true 才能展示给用户。前端选中某档后用
  // getTranscodedStreamUrl(id, resolution) 拼出最终播放 URL。
  getStreamingQualities: async (
    id: string,
    resolution?: string,
  ): Promise<StreamingQualitiesResponse | null> => {
    let url = `/v1/resources/${id}/streaming-qualities`;
    if (resolution) url += `?resolution=${encodeURIComponent(resolution)}`;
    return await fetchApi<StreamingQualitiesResponse>(url);
  },

  // 拼出 302 转码播放 URL。同步函数：videoUrl useMemo 直接调，不用 await。
  // resolution 不传时后端用 default_resolution。
  getTranscodedStreamUrl: (id: string, resolution?: string): string => {
    const base = `${getApiBase()}/v1/resources/${id}/stream-transcoded`;
    return resolution ? `${base}?resolution=${encodeURIComponent(resolution)}` : base;
  },

  getAudioTranscodeDiagnostics: async (id: string): Promise<any | null> => {
    return await fetchApi<any>(`/v1/resources/${id}/audio-transcode/diagnostics`);
  },

  getGovernanceSummary: async (liveCheck: boolean = false): Promise<any | null> => {
    let url = `/v1/resources/governance-summary`;
    if (liveCheck) url += `?live_check=true`;
    return await fetchApi<any>(url);
  },

  listGovernanceItems: async (page = 1, pageSize = 20, issueCode?: string, liveCheck: boolean = false): Promise<{items: any[], meta: any}> => {
    let url = `/v1/resources/governance-items?page=${page}&page_size=${pageSize}`;
    if (issueCode) url += `&issue_code=${issueCode}`;
    if (liveCheck) url += `&live_check=true`;
    
    const data = await fetchApi<any>(url);
    if (!data) return { items: [], meta: null };
    return {
      items: data.items || [],
      meta: data.meta || data.pagination
    };
  },

  planGovernanceCleanup: async (options: any): Promise<any | null> => {
    return await fetchApi<any>('/v1/resources/governance/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  },

  startGovernanceCleanupJob: async (options: any): Promise<components["schemas"]["BackgroundJobResponse"] | null> => {
    return await fetchApi<any>('/v1/resources/governance/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  },

  startGovernanceLiveCheckJob: async (options: any): Promise<components["schemas"]["BackgroundJobResponse"] | null> => {
    return await fetchApi<any>('/v1/resources/governance/live-check/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  },

  planGovernanceRestore: async (options: any): Promise<any | null> => {
    return await fetchApi<any>('/v1/resources/governance/restore/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  },

  startGovernanceRestoreJob: async (options: any): Promise<components["schemas"]["BackgroundJobResponse"] | null> => {
    return await fetchApi<any>('/v1/resources/governance/restore/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options)
    });
  }
};


