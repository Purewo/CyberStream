import { registerPlugin } from '@capacitor/core';
import type { PluginListenerHandle } from '@capacitor/core';

export interface AndroidPlaybackVariant {
  id: string;
  label?: string;
  url: string;
  mimeType?: string;
  userAgent?: string;
  headers?: Record<string, string>;
  isDefault?: boolean;
}

export interface AndroidPlaybackCloudTranscode {
  supported: true;
  provider?: string;
  providerName?: string;
  /** Ticketed absolute endpoint. Native loads it lazily for the active file. */
  qualitiesUrl: string;
  /** Ticketed absolute provider-transcode redirect endpoint. */
  streamUrl: string;
  resolutionParam?: string;
}

export interface AndroidPlaybackTechnical {
  filename?: string;
  sizeBytes?: number;
  storageSource?: string;
  container?: string;
  badges?: string[];
  videoResolution?: string;
  videoCodec?: string;
  dynamicRange?: string;
  bitDepth?: string;
  audioCodec?: string;
  audioChannels?: string;
  audioSummary?: string;
  sourceLabel?: string;
  qualityTier?: string;
}

export interface AndroidPlaybackSubtitle {
  id: string;
  label?: string;
  language?: string;
  format?: string;
  mimeType?: string;
  url: string;
  isDefault?: boolean;
  isForced?: boolean;
  supported?: boolean;
}

export interface AndroidOnlineSubtitleConfig {
  /** Ticketed endpoint used by the native player to search SubHD/SrtKu. */
  searchUrl: string;
  /** Ticketed download endpoint used for a temporary, non-binding preview. */
  downloadUrl: string;
  /** Ticketed endpoint used after the user explicitly chooses a candidate. */
  bindUrl: string;
  /** API base used to resolve relative subtitle stream URLs returned by bind. */
  apiBaseUrl: string;
  /** Editable initial query shown in the phone/tablet search sheet. */
  defaultKeyword?: string;
  providers?: string[];
}

export interface AndroidPlaybackResource {
  id: string;
  title?: string;
  episode?: string;
  season?: number;
  badges?: string[];
  direct: AndroidPlaybackVariant;
  subtitles?: AndroidPlaybackSubtitle[];
  onlineSubtitles?: AndroidOnlineSubtitleConfig;
  technical?: AndroidPlaybackTechnical;
  cloudTranscode?: AndroidPlaybackCloudTranscode;
}

export interface AndroidPlaybackSeason {
  season: number;
  displayTitle: string;
  resourceIds: string[];
}

export interface AndroidPlaybackSession {
  version: 2;
  sessionId: string;
  initialResourceId: string;
  startTimeMs: number;
  contentKind: 'movie' | 'series';
  movie: {
    id: string;
    title: string;
    posterUrl?: string;
    seasons?: AndroidPlaybackSeason[];
  };
  resources: AndroidPlaybackResource[];
}

export interface AndroidPlaybackResult {
  sessionId: string;
  resourceId?: string;
  positionMs?: number;
  durationMs?: number;
  ended?: boolean;
  authExpired?: boolean;
  error?: string;
}

export interface AndroidPlaybackProgress {
  sessionId: string;
  resourceId: string;
  positionMs: number;
  durationMs: number;
  state: 'playing' | 'paused' | 'ended';
}

interface CyberPlayerPlugin {
  open(options: { session: AndroidPlaybackSession }): Promise<AndroidPlaybackResult>;
  openExternalUrl(options: { url: string }): Promise<void>;
  addListener(
    eventName: 'progress',
    listenerFunc: (event: AndroidPlaybackProgress) => void,
  ): Promise<PluginListenerHandle>;
}

const CyberPlayer = registerPlugin<CyberPlayerPlugin>('CyberPlayer');

export const launchAndroidPlayer = (session: AndroidPlaybackSession): Promise<AndroidPlaybackResult> =>
  CyberPlayer.open({ session });

export const openAndroidExternalUrl = (url: string): Promise<void> =>
  CyberPlayer.openExternalUrl({ url });

export const onAndroidPlaybackProgress = (
  listener: (event: AndroidPlaybackProgress) => void,
): Promise<PluginListenerHandle> => CyberPlayer.addListener('progress', listener);
