import { ReactNode } from 'react';

export interface ThemeConfig {
  primary: string;
  secondary: string;
  bg: string;
  text: string;
  accent: string;
}

export interface TechSpecs {
  resolution?: string;
  codec?: string;
  codec_label?: string;
  size?: string;
  size_bytes?: number;
  audio?: string;
  audio_summary?: string;
  bitrate?: string;
  container?: string;
  hdr?: string;
  source_label?: string;
  bit_depth?: string;
  storage_name?: string;
  flag_is_4k?: boolean;
  flag_is_remux?: boolean;
  flag_is_hdr?: boolean;
  flag_is_dolby_vision?: boolean;
  audio_is_atmos?: boolean;
  video_dynamic_range_label?: string;
  extra_tags?: string[];
}

export interface MediaInfo {
  video_codec?: string;
  audio_codec?: string;
  resolution?: string;
  bitrate?: number;
  hdr?: string;
}

export interface PlaybackUserData {
  last_played_at?: string;
  resource_id?: string;
  season?: number;
  episode?: number;
  episode_label?: string;
  label?: string;
  filename?: string;
  progress: number;
  duration: number;
  position_sec: number;
  duration_sec: number;
  progress_ratio?: number;
  progress_percent?: number;
  seasons?: PlaybackUserData[];
}

export interface ResourceSubtitleItem {
  id: string;
  source: 'sidecar' | 'online_bound';
  match?: string;
  filename: string;
  path?: string;
  format: 'srt' | 'ass' | 'ssa' | 'vtt' | 'sub' | 'sup';
  mime_type: string;
  language?: any;
  label: string;
  is_default: boolean;
  is_forced: boolean;
  url: string;
  web_player?: any;
  storage?: any;
  online?: any;
}

export interface ResourceSubtitlePlayback {
  items: ResourceSubtitleItem[];
  default_subtitle_id?: string;
  web_player_supported: boolean;
  discovery?: any;
}

export interface ResourcePlayback {
  stream_url: string | null;
  mime_type?: string;
  storage_type?: string;
  playback_modes?: string[];
  default_mode?: string;
  web_player?: {
    needs_server_audio_transcode: boolean;
    // 原始文件能否在网页 <video> 直接播。阿里=true（原文件可播），
    // 夸克/UC=false（原始下载链被反爬挡，必须走 cloud_transcode）。
    supported?: boolean;
    reason?: string | null;
  };
  external_player?: any;
  subtitles?: ResourceSubtitlePlayback;
  audio?: {
    web_decode_status?: string;
    web_decode_risk?: boolean;
    server_transcode?: {
      endpoint: string;
      url: string;
      start_param: string;
      audio_track_param: string;
      format_param: string;
      session_param: string;
      mime_type: string;
      sync_strategy: string;
    };
  };
  // 云转码契约。后端按来源分发，凡 cloud_transcode.supported=true 即提供多档
  // 转码清晰度入口（quarktv/uctv 走 TV provider API，aliyundrive 走 OpenList
  // video_preview）。档位名因来源而异（夸克 low/normal/high/super/2k/4k，阿里
  // ld/sd/hd/fhd/qhd/4k）——前端只看 supported + 遍历 items，禁止硬编码网盘类型
  // 或清晰度枚举。详见 GET /v1/docs/frontend-managed-quark-uc / -aliyundrive。
  cloud_transcode?: {
    supported: boolean;
    provider?: string;
    provider_name?: string;
    mode?: string;
    qualities_endpoint?: string;
    stream_endpoint?: string;
    resolution_param?: string;
    available_resolutions?: string[];
  };
}

export interface Resource {
  id: string;
  filename: string;
  source_id: number;
  source_name: string;
  protocol: string;
  relative_path: string;
  display_label?: string;
  quality_label?: string;
  size_bytes?: number;
  container?: string;
  media_info?: MediaInfo;
  resource_info?: any;
  season?: number;
  episode?: number;
  playback?: ResourcePlayback;
  user_data?: PlaybackUserData;
}

export interface Genre {
  name: string;
  slug: string;
  count: number;
}

export interface Region {
  name: string;
  code: string;
  count: number;
}

export interface YearStats {
  year: number;
  count: number;
}

export interface FilterDictionaries {
  genres: Genre[];
  years: YearStats[];
  countries: Region[];
  metadata_issue_codes?: { code: string, count: number }[];
}

export interface MovieRecommendationReason {
  code: string;
  label: string;
  detail?: string | null;
  weight?: number | null;
}

export interface MovieRecommendationSignals {
  progress_ratio?: number;
  quality_badge?: string;
  resource_count?: number;
}

export interface MovieRecommendation {
  strategy: 'default' | 'latest' | 'top_rated' | 'surprise' | 'continue_watching' | 'context';
  rank?: number;
  score?: number;
  primary_reason?: MovieRecommendationReason;
  reasons?: MovieRecommendationReason[];
  reason_text?: string;
  signals?: MovieRecommendationSignals;
}

export interface MetadataState {
  source_code?: string | null;
  source_group?: string;
  source_label?: string;
  is_placeholder?: boolean;
  is_local_only?: boolean;
  is_external_match?: boolean;
  confidence?: string;
  needs_attention?: boolean;
  review_priority?: 'none' | 'low' | 'medium' | 'high';
  badge_tone?: 'success' | 'brand' | 'info' | 'warning' | 'danger';
  recommended_action?: 'none' | 'review_match' | 'match_metadata' | 'rename_and_match' | 'refresh_metadata' | 'inspect_metadata';
  issue_count?: number;
  issue_codes?: string[];
  primary_issue_code?: string | null;
}

// 目录可见性。后端 1.21 加入 pending_review 状态：批量刮削/低置信结果默认
// 进待审批池，不出现在 /api/v1/movies 普通影视库列表里，等用户在「待审批」
// tab 多选确认后批量发布到普通库。
// - status='auto': 后端按规则自动判断 effective_status (auto_public / pending_review)
// - status='published': 管理员显式发布；有 blockers 时需要 force=true
// - status='pending_review': 待审批池
// - status='hidden': 显式隐藏，不进普通库
export type CatalogStatus = 'auto' | 'published' | 'pending_review' | 'hidden';
export interface CatalogVisibility {
  status: CatalogStatus;
  effective_status: CatalogStatus | 'auto_public';
  is_visible: boolean;
  is_manual: boolean;
  auto_visible?: boolean;
  can_publish?: boolean;
  requires_force?: boolean;
  reason?: string | null;
  note?: string | null;
  // 后端实际返字符串数组（issue code），非 {code,label} 对象。
  // 例：["metadata_needs_attention", "poster_missing"]
  blockers?: string[];
  warnings?: string[];
  updated_at?: string | null;
}

export interface Movie {
  id: string | number;
  title: string;
  original_title?: string;
  rating: string; // Mapped from number
  year: number;
  date_added?: string; // New field for sorting by added date
  duration?: string | number;
  quality_badge?: string; // New feature in 1.16.0-beta
  recommendation?: MovieRecommendation;
  tags?: string[];
  desc?: string; // Mapped from overview
  overview?: string; // Raw API field
  cast?: string[];
  director?: string;
  poster_url?: string; // Raw API field
  backdrop_url?: string; // Raw API field
  poster_asset_url?: string; // Backend stable poster resource URL
  backdrop_asset_url?: string; // Backend stable backdrop resource URL
  poster_source_info?: any;
  backdrop_source_info?: any;
  cover_url?: string; // Mapped from poster_url for UI compat
  resources?: Resource[];
  type?: string;
  region?: string;
  tech_specs?: TechSpecs;
  views?: string;
  trend?: 'up' | 'down' | 'stable';
  change?: string;
  source_path?: string; // Legacy compat
  lastPlayedAt?: string;
  source_ids?: number[];
  isUnscraped?: boolean;
  metadata_locked_fields?: string[];
  metadata_unlocked_fields?: string[];
  target_season?: number;
  has_multi_season_content?: boolean;
  season_cards?: SeasonCard[];
  user_data?: PlaybackUserData;
  metadata_state?: MetadataState;
  catalog_visibility?: CatalogVisibility;
  manual_content?: boolean;
}

export interface SeasonCard {
  id: string;
  movie_id: string;
  season: number;
  title: string | null;
  display_title: string;
  overview: string | null;
  air_date: string | null;
  poster_url: string | null;
  poster_source: 'season' | 'movie_fallback' | 'none';
  has_distinct_poster: boolean;
  resource_count: number;
  available_episode_count: number;
  episode_count: number | null;
  episode_numbers: number[];
  primary_resource_id: string | null;
  has_manual_metadata: boolean;
  has_metadata: boolean;
  metadata_edited_at: string | null;
  user_data?: PlaybackUserData;
}

export interface MovieMetadataWorkItem {
  movie: any;
  review_priority?: string;
  resolution_classification?: {
    code: string;
    description?: string;
  };
  tmdb_id?: number | null;
  movie_id?: number;
  manual_content?: boolean;
}

export interface Category {
  id: string;
  title: string;
  icon: ReactNode;
  colorClass: string;
  bgClass: string;
  keywords: string[];
}

export interface Achievement {
  id: string;
  title: string;
  desc: string;
  icon: string; // lucide-react 图标名字符串，UI 层映射成组件
  category: 'behavior' | 'milestone';
  trigger?: {
    metric: string;
    op: '>=' | '==';
    value: number;
  };
  unlocked: boolean;
  unlockedAt: string | null;
  progress: number; // 0..1，未解锁的 milestone 进度；behavior 已解锁固定为 1
}

export interface AchievementSummary {
  total: number;
  unlocked: number;
  milestones: number;
  behaviors: number;
  newlyUnlockedIds: string[];
}

export interface Episode {
  id: string | number;
  resourceId?: string; // Link to backend Resource ID
  path: string;
  title: string;
  label: string;
  size?: string;
}

// 云转码可选画质列表（GET /v1/resources/{id}/streaming-qualities）。
// 凡 cloud_transcode.supported=true 的来源都返回（夸克/UC/阿里等）；档位名因
// 来源而异，前端遍历 items 即可，不要枚举 resolution 取值。
export interface StreamingQualityItem {
  resolution: string; // 夸克: low/normal/high/super/2k/4k；阿里: ld/sd/hd/fhd/qhd/4k
  label?: string;
  available: boolean;
  width?: number;
  height?: number;
  size?: number;
  bitrate?: number;
  format?: string;
  trans_status?: string;
  stream_url?: string; // CyberStream 302 endpoint：/v1/resources/{id}/stream-transcoded?resolution=...
  url?: string;        // 上游直链（可能过期），优先用 stream_url
}
export interface StreamingQualitiesResponse {
  resource_id: string;
  storage_type?: string;
  provider?: string;
  mode?: string;
  default_resolution?: string;
  selected_resolution?: string;
  items: StreamingQualityItem[];
}

export interface HistoryItem extends Movie {
  progress: number;
  duration: number;
  time_str: string;
  date?: string;
  resourceId: string;
  updated_at?: string;
}

export interface Notification {
  id: string;
  type: 'system' | 'content' | 'maintenance' | 'info';
  title: string;
  time: string;
  desc: string;
  details?: string;
}

export interface PlayOptions {
  startTime?: number;
  resourceId?: string;
}

export interface SeasonMetadata {
  season: number;
  title?: string;
  display_title: string;
  overview?: string;
  air_date?: string;
  has_manual_metadata: boolean;
  metadata_edited_at?: string;
}

export interface SeasonGroup extends SeasonMetadata {
  items: Resource[];
  resource_ids: string[];
  episode_count: number;
  edited_items_count: number;
  user_data?: PlaybackUserData;
}

export interface MovieResourceGroupsSummary {
  total_items: number;
  season_count: number;
  standalone_count: number;
  edited_items_count: number;
  season_metadata_count: number;
  metadata_source_group: string;
  needs_attention: boolean;
  review_priority: 'none' | 'low' | 'medium' | 'high';
}

export interface StandaloneResourceGroup {
  resource_ids: string[];
  count: number;
}

export interface MovieResourceGroupIndex {
  standalone: StandaloneResourceGroup;
  seasons: SeasonGroup[];
}

export interface MovieResourceGroups {
  items: Resource[];
  groups: MovieResourceGroupIndex;
  summary: MovieResourceGroupsSummary;
}

export interface MetadataOverview {
  total_movies: number;
  total_resources: number;
  needs_attention_count: number;
  source_distribution: Record<string, number>;
  priority_distribution: Record<string, number>;
}

export interface UserSettings {
  scanlines: boolean;
  glitch: boolean;
  /** 个人偏好 — 主页/库默认行为，本地 localStorage 持久化（区别于服务端的 hero/sections）。 */
  homepage?: HomepageUserPrefs;
}

/** 个人偏好（本地）。和服务端 HomepageConfig 是两件事——前者是"我打开应用想直接看到啥"，
 *  后者是"首页 hero + 分类区块全用户共享配置"。 */
export interface HomepageUserPrefs {
  /** 启动后默认打开的视图。`library:<id>` 表示直接进某个具体片库。 */
  defaultLanding?: 'home' | 'library' | `library:${number}`;
  /** 进 library 视图时的初始筛选。 */
  libraryDefaults?: {
    type?: string;       // genre 名（"全部类型"含义见 Library.tsx）
    sort?: string;       // FILTERS 里的 sort id
  };
}

/** 服务端 /api/v1/homepage/config 的 schema 镜像。 */
export interface HomepageSectionConfig {
  key: string;
  title: string;
  genre?: string;
  mode: 'latest' | 'custom';
  limit: number;            // 1-20
  movie_ids?: string[];
  enabled: boolean;
  sort_order: number;
}

export interface HomepageConfig {
  hero_movie_id: string | null;
  sections: HomepageSectionConfig[];
  created_at?: string | null;
  updated_at?: string | null;
}

export type ViewState = 'home' | 'library' | 'leaderboard' | 'history' | 'profile' | 'detail' | 'player' | 'search' | 'review' | 'libraries' | 'add_library';

export interface StorageConfigField {
  name: string;
  type: string;
  required: boolean;
  default?: any;
  description?: string;
}

export interface FileItem {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: number | null;
  last_modified?: string | null;
  extension?: string | null;
  mime_type?: string | null;
}

export interface StorageProviderCapabilities {
  preview: boolean;
  scan: boolean;
  stream: boolean;
  ffmpeg_input: boolean;
  credentials_required: boolean;
  health_check: boolean;
}

export interface StorageProviderType {
  type: string;
  display_name: string;
  status: string;
  config_fields: StorageConfigField[];
  capabilities: StorageProviderCapabilities;
}

export interface StorageSourceActions {
  can_preview: boolean;
  can_scan: boolean;
  can_stream: boolean;
}

export interface StorageSourceHealth {
  status: 'online' | 'offline' | 'unknown' | 'unsupported';
  reason?: string;
  message?: string;
}

export interface StorageSourceUsage {
  library_binding_count: number;
  resource_count: number;
  has_resources: boolean;
}

export interface StorageSourceGuards {
  can_change_type: boolean;
  can_delete_directly: boolean;
  requires_keep_metadata_on_delete: boolean;
  has_dependents: boolean;
}

export interface Library {
  id: number;
  name: string;
  slug: string;
  description?: string;
  is_enabled: boolean;
  sort_order: number;
  settings: any;
  created_at?: string;
  updated_at?: string;
}

export interface LibrarySourceBinding {
  id: number;
  library_id: number;
  source_id: number;
  root_path: string;
  content_type?: string;
  scrape_enabled: boolean;
  scan_order: number;
  is_enabled: boolean;
  created_at?: string;
  source?: StorageSource;
}

export interface StorageSource {
  id: number;
  name: string;
  type: string;
  root_path?: string;
  status?: string;
  display_name?: string;
  is_supported?: boolean;
  capabilities?: StorageProviderCapabilities;
  config?: any;
  actions?: StorageSourceActions;
  health?: StorageSourceHealth;
  config_valid?: boolean;
  config_error?: string;
  usage?: StorageSourceUsage;
  guards?: StorageSourceGuards;
}

export interface ScanActiveItem {
  id?: string;
  name?: string;
}

export interface PathCleaningAnalysis {
  title_hint?: string | null;
  year_hint?: number | null;
  season_hint?: number | null;
  episode_hint?: number | null;
  parse_mode?: string;
  parse_strategy?: string;
  needs_review?: boolean;
}

export interface ScrapingAnalysis {
  provider?: string | null;
  confidence?: number | null;
  matched_id?: string | null;
  warnings?: string[];
  final_title_source?: string | null;
  final_year_source?: string | null;
  provider_order?: string[];
}

export interface ReviewResourceItem {
  resource_id: number;
  movie_id?: string | null;
  movie_title?: string | null;
  movie_original_title?: string | null;
  movie_year?: number | null;
  filename: string;
  relative_path: string;
  source_id?: number | null;
  source_name: string;
  quality_label?: string | null;
  path_cleaning?: PathCleaningAnalysis;
  scraping?: ScrapingAnalysis;
}

export interface ReviewResourceListResponse {
  items: ReviewResourceItem[];
  pagination?: {
    total: number;
    page: number;
    limit: number;
    total_pages: number;
  };
}

export interface ScanStatus {
  state: 'idle' | 'scanning' | 'stopping';
  progress?: number;
  current_file?: string;
  speed?: string;
  remaining_time?: string;
}