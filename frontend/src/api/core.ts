import { API_BASE } from '../constants/index';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';
import { formatBytes } from '../utils/index';

// Types defining the raw API response structure based on openapi.json
interface ApiResponse<T> {
  code: number;
  msg: string;
  trace_id?: string;
  data: T;
}

interface ApiPagination {
  current_page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}

interface ApiMovieSimple {
  id: string;
  title: string;
  poster_url?: string;
  rating?: number;
  year?: number;
  date_added?: string;
  source_ids?: number[];
  genres?: string[];
  quality_badge?: string;
  recommendation?: import('../types/index').MovieRecommendation;
  user_data?: {
      last_played_at?: string;
  };
  season_cards?: import('../types/index').SeasonCard[];
  has_multi_season_content?: boolean;
  // Allow loose typing for fields that might exist in backend but not spec yet
  [key: string]: any; 
}

interface ApiMovieDetailed extends ApiMovieSimple {
  original_title?: string;
  overview?: string;
  backdrop_url?: string;
  resources?: Resource[];
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) {
      console.warn(`API Error ${res.status} on ${path}`);
      return null;
    }
    const json: ApiResponse<T> = await res.json();
    if (json.code !== 200) {
      console.warn(`API Business Error ${json.code}: ${json.msg}`);
      return null;
    }
    return json.data;
  } catch (error) {
    console.error(`Network Error on ${path}`, error);
    return null;
  }
}

// Helper to infer metadata from text content
const inferMetadata = (title: string = '', overview: string = '') => {
  const safeTitle = title || '';
  const safeOverview = overview || '';
  const text = (safeTitle + ' ' + safeOverview).toLowerCase();
  
  const types = [];
  if (/sci-fi|space|future|alien|robot|cyber|star|planet|未来|太空|外星|科幻|赛博/.test(text)) types.push('科幻');
  if (/action|fight|battle|war|kill|gun|hero|动作|战斗|战争/.test(text)) types.push('动作');
  if (/love|romance|kiss|heart|爱情|恋爱/.test(text)) types.push('剧情');
  if (/anime|manga|cartoon|animation|动画|动漫/.test(text)) types.push('动画');
  if (/thriller|horror|ghost|scary|惊悚|恐怖|悬疑/.test(text)) types.push('惊悚');
  
  const regions = [];
  if (/china|chinese|mandarin|cantonese|中国|华语/.test(text)) regions.push('中国');
  if (/hong kong|hk|香港/.test(text)) regions.push('中国'); // Group HK into CN for simple filter, or keep separate if needed
  if (/taiwan|tw|台湾/.test(text)) regions.push('中国');
  if (/japan|japanese|tokyo|日本|日语/.test(text)) regions.push('日本');
  if (/korea|korean|seoul|韩国|韩语/.test(text)) regions.push('韩国');
  if (/usa|america|hollywood|new york|美国|美剧/.test(text)) regions.push('美国');
  if (/uk|united kingdom|britain|london|英国|英剧/.test(text)) regions.push('英国');
  
  const mainType = types[0] || '剧情';
  // Ensure the main type is present in tags
  const finalTags = [...types];
  if (!finalTags.includes(mainType)) {
    finalTags.push(mainType);
  }

  return {
    type: mainType, // Default to Drama
    tags: [...finalTags, ...regions],
    region: regions[0] || '其他'
  };
};

// Helper to parse duration from various formats to seconds
const parseDuration = (val: string | number | undefined): number => {
  if (val === undefined || val === null) return 0;
  if (typeof val === 'number') {
    return isNaN(val) ? 0 : val;
  }
  const str = String(val).trim().toUpperCase();
  if (str === 'N/A' || str === '') return 0;
  
  // Try to find a number at the start
  const match = str.match(/^(\d+(\.\d+)?)/);
  if (!match) return 0;
  
  let num = parseFloat(match[1]);
  
  // Check units
  if (str.includes('MIN')) {
    num *= 60;
  } else if (str.includes('H') && !str.includes('MIN')) { 
     // Handle "2H" or similar if needed, though MIN is standard in this app
     num *= 3600;
  }
  // If no unit, assume seconds if it's from API logic, but if from constants mock it might be mixed.
  // Assuming raw number in string is seconds unless MIN specified.
  
  return Math.floor(num);
};

// Adapter to convert API format to UI Movie format
const mapApiMovieToUi = (apiMovie: ApiMovieSimple | ApiMovieDetailed): Movie => {
  const isDetailed = (m: any): m is ApiMovieDetailed => 'resources' in m;
  
  const safeTitle = apiMovie.title || 'Unknown Title';

  // Use explicit genres from API if available, otherwise fallback to inference
  let type = apiMovie.type;
  let tags = apiMovie.tags || [];
  let region = apiMovie.region;

  if (apiMovie.genres && apiMovie.genres.length > 0) {
    // If API provides genres, use them primarily
    tags = [...apiMovie.genres, ...tags];
    if (!type) type = apiMovie.genres[0];
  }

  // Fallback if still missing info
  if (!type || tags.length === 0 || !region) {
      const inferred = inferMetadata(safeTitle, apiMovie.overview || '');
      if (!type) type = inferred.type;
      if (tags.length === 0) tags = inferred.tags;
      if (!region) region = inferred.region;
  }
  
  // Deduplicate tags
  tags = Array.from(new Set(tags));

  // Build Tech Specs from Resource info if detailed
  let techSpecs: TechSpecs = {};
  if (isDetailed(apiMovie) && apiMovie.resources && apiMovie.resources.length > 0) {
      const bestRes = apiMovie.resources[0] as any; // Using any since we are updating interface
      if (bestRes.resource_info?.technical) {
          const tech = bestRes.resource_info.technical;
          techSpecs = {
              resolution: tech.video_resolution_label || undefined,
              codec: tech.video_codec_label?.toUpperCase(),
              audio: tech.audio_codec_label?.toUpperCase(),
              container: bestRes.container?.toUpperCase(),
              size: bestRes.size_bytes ? formatBytes(bestRes.size_bytes) : undefined,
              hdr: tech.video_dynamic_range_label,
              flag_is_4k: tech.flag_is_4k,
              flag_is_remux: tech.flag_is_remux,
              flag_is_hdr: tech.flag_is_hdr,
              flag_is_dolby_vision: tech.flag_is_dolby_vision,
              audio_is_atmos: tech.audio_is_atmos,
              video_dynamic_range_label: tech.video_dynamic_range_label,
              extra_tags: tech.extra_tags || []
          };
      } else if (bestRes.media_info) {
          techSpecs = {
              resolution: bestRes.media_info.resolution || undefined,
              codec: bestRes.media_info.video_codec?.toUpperCase(),
              audio: bestRes.media_info.audio_codec?.toUpperCase(),
              bitrate: bestRes.media_info.bitrate ? `${(bestRes.media_info.bitrate / 1000).toFixed(1)} Mbps` : undefined,
              container: bestRes.container?.toUpperCase(),
              size: bestRes.size_bytes ? formatBytes(bestRes.size_bytes) : undefined,
              hdr: bestRes.media_info.hdr
          };
      } else if (bestRes.display_label || bestRes.quality_label) {
          techSpecs.resolution = bestRes.display_label || bestRes.quality_label;
      }
  } else if (apiMovie.tech_specs) {
      // Legacy or pre-computed field support
      techSpecs = apiMovie.tech_specs;
  }

  return {
    id: apiMovie.id || `unknown-${Math.random()}`,
    title: safeTitle,
    original_title: apiMovie.original_title,
    rating: apiMovie.rating ? Number(apiMovie.rating).toFixed(1) : '0.0',
    year: apiMovie.year || new Date().getFullYear(),
    date_added: apiMovie.date_added, // Map date_added for sorting
    cover_url: apiMovie.poster_url || '', // Map poster to cover
    poster_url: apiMovie.poster_url,
    backdrop_url: apiMovie.backdrop_url,
    desc: apiMovie.overview || apiMovie.desc || '',
    overview: apiMovie.overview || apiMovie.desc || '',
    resources: apiMovie.resources || [],
    duration: apiMovie.duration || 'N/A', 
    quality_badge: apiMovie.quality_badge,
    tags: tags,
    type: type,
    region: region,
    views: 'N/A',
    lastPlayedAt: apiMovie.user_data?.last_played_at,
    tech_specs: techSpecs,
    source_ids: apiMovie.source_ids,
    isUnscraped: !apiMovie.poster_url && !apiMovie.overview,
    metadata_locked_fields: apiMovie.metadata_locked_fields,
    metadata_unlocked_fields: apiMovie.metadata_unlocked_fields,
    target_season: apiMovie.user_data?.season,
    user_data: apiMovie.user_data,
    has_multi_season_content: apiMovie.has_multi_season_content,
    season_cards: apiMovie.season_cards,
    recommendation: apiMovie.recommendation,
    metadata_state: apiMovie.metadata_state
  };
};

const mapSeasonCardToUi = (sc: import('../types/index').SeasonCard, parent: ApiMovieSimple): Movie => {
  const base = mapApiMovieToUi(parent);
  let resolvedPoster = sc.poster_url || base.poster_url;
  if (!sc.has_distinct_poster && sc.poster_source === 'movie_fallback') {
      resolvedPoster = base.poster_url;
  }

  return {
    ...base,
    id: `${parent.id}-S${sc.season}`, // Unique ID for UI lists
    target_season: sc.season,
    title: sc.display_title || base.title,
    cover_url: resolvedPoster || '',
    poster_url: resolvedPoster || '',
    desc: sc.overview || base.desc,
    overview: sc.overview || base.overview,
    has_multi_season_content: false, // Don't re-flatten
  };
};

const getDeviceId = () => {
    let id = localStorage.getItem('cyber_device_id');
    if (!id) {
        id = crypto.randomUUID();
        localStorage.setItem('cyber_device_id', id);
    }
    return id;
};


export { fetchApi, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId };
export type { ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse };
