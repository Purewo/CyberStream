import React, { useEffect, useRef, useState } from 'react';
import Navbar, { Footer } from './components/layout/Navbar';
import { Home, Library, Leaderboard, HistoryPage, SearchResults, ReviewWorkbench } from './features/Views';
import { ProfilePage } from './features/Profile';
import { MovieDetail } from './features/MovieDetail';
import { MetadataEditor } from './features/MetadataEditor';
import { Player } from './components/Player';
import { LibrariesList } from './features/LibrariesList';
import { AddLibraryWizard } from './features/AddLibraryWizard';
import { AddToLibraryModal } from './features/AddToLibraryModal';
import { ContextMenu } from './components/ui/ContextMenu';
import { ScanProgressBar } from './components/ui/ScanProgressBar';
import { BackgroundJobProgressBar } from './components/ui/BackgroundJobProgressBar';
import { Toaster } from './components/ui/Toaster';
import { movieService, libraryService, userService, resourceService, storageService, ensureTicket, appendTicket, invalidateTicket } from './api';
import { authService, AuthStatus } from './api/auth';
import { Login } from './features/Login';
import { getDeviceId, resolveAssetUrl } from './api/core';
import { getPublicUrlBase, writeClipboard, platform, getApiBase } from './platform';
import { launchNativePlayer, needsUserAgentRewrite, pickUserAgentForRewrite } from './platform/nativePlayer';
import {
  launchAndroidPlayer,
  onAndroidPlaybackProgress,
} from './platform/androidPlayer';
import type { AndroidPlaybackSeason } from './platform/androidPlayer';
import { getStyles, toast } from './utils';
import { useGlobalHotkeys } from './hooks/useGlobalHotkeys';
import { Movie, ViewState, PlayOptions, Resource, StorageSource, MovieResourceGroups } from './types';
import { useThemeSettings } from './hooks/useThemeSettings';
import { useUserData } from './hooks/useUserData';
import { useAppRouting } from './hooks/useAppRouting';
import { TMDBMatchModal } from './features/TMDBMatchModal';

interface AndroidPlaybackCatalog {
  resources: Resource[];
  seasons: AndroidPlaybackSeason[];
}

const withTimeout = async <T,>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((resolve) => { timer = setTimeout(() => resolve(fallback), timeoutMs); }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
};

const App = () => {
  const { settings, setSettings, themeName, setThemeName, currentTheme } = useThemeSettings();
  useGlobalHotkeys();

  // 鉴权门：null=未探测，true=可进入主体，false=要求登录。
  // 启动时被动探测 /auth/me；user_management_enabled=false 直接放行（旧模式）。
  // 调试旁路：URL 带 ?force_login=1 时直接渲染登录页（视觉验收用，不参与生产逻辑）。
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const forceLogin = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('force_login') === '1';
  const requireLogin = forceLogin || (!!authStatus && authStatus.user_management_enabled && !authStatus.authenticated);

  useEffect(() => {
    let cancelled = false;
    authService.getStatus().then(s => {
      if (cancelled) return;
      // 后端不可达时 s=null：先按"用户管理未启用"放行，避免登录页阻塞所有自托管/本地开发环境。
      // 真有后端要求会在受保护接口 401 时再回弹。
      if (!s) {
        setAuthStatus({
          user_management_enabled: false,
          authenticated: false,
          role: null,
          auth_via: null,
          user: null,
          permissions: { admin: false, read_catalog: false, manage_catalog: false, manage_users: false, personal_history: false, personal_subtitle_settings: false },
        });
      } else {
        setAuthStatus(s);
      }
      setAuthReady(true);
    });
    return () => { cancelled = true; };
  }, []);

  const {
    favorites, handleToggleFavorite, refreshFavorites,
    history, setHistory, handleClearHistory, handleDeleteHistoryItem, refreshHistory,
    notifications,
    libraries, setLibraries, refreshLibraries,
    vaultState, refreshVaultStatus,
  } = useUserData();

  const {
    currentView, setCurrentView,
    profileInitialTab, setProfileInitialTab,
    profileOpenAddResource, setProfileOpenAddResource,
    overlayView, setOverlayView,
    scrollContainerRef, savedScroll, setSavedScroll,
    libraryInitialType, setLibraryInitialType,
    selectedMovie, setSelectedMovie,
    activeLibraryId, setActiveLibraryId,
    searchQuery, setSearchQuery,
    searchResults, setSearchResults,
    playOptions, setPlayOptions,
    contextMenu, setContextMenu,
    metadataMovie, setMetadataMovie,
    matchMovie, setMatchMovie,
    addToLibraryMovie, setAddToLibraryMovie,
    navigateTo, closeOverlay, openMovie: handleMovieSelect, openPlayer
  } = useAppRouting();

  const lastAndroidHistoryPositionRef = useRef(new Map<string, number>());
  const androidPlaybackBusyRef = useRef(false);

  // Media3 runs in a separate Android Activity. It sends a lightweight
  // progress event while visible; the final position is also returned by the
  // open() promise when the Activity closes. We deliberately report through
  // the WebView so HttpOnly login cookies never cross the JS/native boundary.
  useEffect(() => {
    if (platform().kind !== 'android') return;
    let disposed = false;
    let listener: { remove: () => Promise<void> } | null = null;

    void onAndroidPlaybackProgress((event) => {
      if (event.positionMs < 5_000 || event.durationMs <= 0) return;
      const key = `${event.sessionId}:${event.resourceId}`;
      const previousPosition = lastAndroidHistoryPositionRef.current.get(key);
      // Media3 can emit the same paused/ended state repeatedly while its
      // activity remains open. Avoid issuing identical history writes, while
      // still accepting a meaningful seek backwards or forwards.
      if (previousPosition != null && Math.abs(previousPosition - event.positionMs) < 1_000) return;
      lastAndroidHistoryPositionRef.current.set(key, event.positionMs);
      void userService.reportHistory(
        event.resourceId,
        event.positionMs / 1000,
        event.durationMs / 1000,
        event.sessionId,
      );
    }).then((handle) => {
      if (disposed) void handle.remove();
      else listener = handle;
    }).catch((error) => {
      console.warn('[android] unable to subscribe to native player progress', error);
    });
    return () => {
      disposed = true;
      if (listener) void listener.remove();
    };
  }, []);


  // Apply user-preferred default landing on first mount.
  // settings.homepage.defaultLanding 形如 'home' | 'libraries' | 'library' | 'library:42'。
  // 只在首次挂载（currentView === 'home'）时跳，避免覆盖用户已经在浏览的视图。
  useEffect(() => {
    const landing = settings.homepage?.defaultLanding;
    if (!landing || landing === 'home') return;
    if (landing === 'libraries') {
      navigateTo('libraries');
    } else if (landing === 'library') {
      navigateTo('library', { libraryId: null });
    } else if (landing.startsWith('library:')) {
      const id = parseInt(landing.split(':')[1] || '', 10);
      if (!isNaN(id)) navigateTo('library', { libraryId: id });
    }
    // 只在首次挂载执行；不依赖 settings/navigateTo 后续变化（避免设置改了又把用户拽回去）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // PC 冷启动 splash：React mount + 首次 paint 落地后通知 Rust 关 splash 显主窗。
  // requestAnimationFrame 双套一层，确保浏览器 layout/paint 至少跑过一帧，避免
  // splash 关掉的瞬间用户看到一个还没着色完的空架子。
  useEffect(() => {
    if (platform().kind !== 'pc') return;
    const raf1 = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        import('./platform/pc').then(m => m.signalSplashDone()).catch(() => {});
      });
    });
    return () => cancelAnimationFrame(raf1);
  }, []);


  // Global Context Menu Event Listener
  useEffect(() => {
    const handleContextMenuEvent = (e: CustomEvent) => {
      setContextMenu({ visible: true, x: e.detail.x, y: e.detail.y, movie: e.detail.movie });
    };
    window.addEventListener('show-movie-context-menu', handleContextMenuEvent as EventListener);
    return () => window.removeEventListener('show-movie-context-menu', handleContextMenuEvent as EventListener);
  }, []);

  // 扫描结束后：把当前页面的数据刷新一遍，免得用户手动 F5。
  // ScanProgressBar 完成时派发 cyber:scan:completed；这里转成 library-list-dirty
  // 让 Library 列表重新拉一次，并 refreshLibraries 同步左侧虚拟库列表，
  // 同时让 Home 重新拉首页（监听器在 Home 自己里）。
  useEffect(() => {
    const handleScanCompleted = () => {
      window.dispatchEvent(new CustomEvent('library-list-dirty'));
      refreshLibraries();
    };
    window.addEventListener('cyber:scan:completed', handleScanCompleted);
    return () => window.removeEventListener('cyber:scan:completed', handleScanCompleted);
  }, [refreshLibraries]);
  

  const handleSearch = async (query: string) => { 
    setSearchQuery(query); 
    navigateTo('search'); 
    try { 
      const data = await movieService.search(query); 
      setSearchResults(data); 
    } catch (e) { 
      console.error("Search failed", e); 
    } 
  }; 
  

  
  const handleNavigate = (view: ViewState) => { 
    if (view === 'history') { 
      refreshHistory();
    } 
    navigateTo(view); 
  }; 
  
  const handleViewCategory = (categoryId: string) => {
    // 后端 homepage 返回的 section.genre 已是中文标签（科幻/动作/剧情/动画），直接当 type 过滤；
    // 老英文 key 兜底兼容历史调用方
    const legacyMapping: Record<string, string> = { scifi: '科幻', sci_fi: '科幻', action: '动作', romance: '剧情', drama: '剧情', anime: '动画', animation: '动画' };
    const filterLabel = legacyMapping[categoryId] || categoryId || '全部类型';
    navigateTo('library', { libraryInitialType: filterLabel });
  };
  
  const handleContextMenuAction = async (action: string, movie: Movie) => {
    setContextMenu(prev => ({ ...prev, visible: false }));
    switch (action) {
       case 'add_to_library':
         if (libraries.length === 0) {
           toast.info("当前没有任何专辑，请先创建专辑。");
           navigateTo('libraries');
         } else {
           setAddToLibraryMovie(movie);
         }
         break;
       case 'remove_from_library':
         if (activeLibraryId) {
           // We attempt to delete any manual include/exclude rule first
           await libraryService.deleteMovieMemberships(activeLibraryId, [String(movie.id)]);
           // Then we explicitly exclude it to override directory matches
           const success = await libraryService.createMovieMembership(activeLibraryId, 'exclude', [String(movie.id)]);
           if (success) {
             toast.success(`《${movie.title}》已从当前专辑移除。`);
             window.dispatchEvent(new CustomEvent('library-list-dirty'));
           } else {
             toast.error("移除失败，请重试。");
           }
         }
         break;
       case 'scrape':
         setMatchMovie(movie);
         break;
       case 'sync_resources': {
         toast.info(`正在同步《${movie.title}》的资源...`);
         const result = await movieService.syncResources(movie.id);
         if (result.ok) {
           toast.success(`《${movie.title}》资源同步任务已下发，可在扫描进度处查看。`);
         } else if (result.status === 429) {
           toast.error('扫描器正忙，请等当前任务结束后重试。');
         } else if (result.status === 400) {
           toast.error(result.msg || '该影片没有可同步的资源路径。');
         } else {
           toast.error(result.msg || '资源同步任务下发失败。');
         }
         break;
       }
       case 'edit':
         setMetadataMovie(movie);
         break;
       case 'share':
         try {
           const origin = getPublicUrlBase();
           const link = origin ? `${origin}/movie/${movie.id}` : `/movie/${movie.id}`;
           await writeClipboard(`你看《${movie.title}》了吗？超赞：${link}`);
           toast.success('分享链接已复制到剪贴板');
         } catch {
           toast.error('复制失败，请检查剪贴板权限');
         }
         break;
       case 'favorite':
         await handleToggleFavorite(movie);
         break;
       case 'watched':
         // Simulate marking as watched locally + report to API if possible
         await userService.reportHistory(String(movie.id), Number(movie.duration) || 3600, Number(movie.duration) || 3600);
         {
           const now = new Date();
           setHistory(prev => [{
             ...movie,
             resourceId: String(movie.id),
             progress: 1,
             duration: 1,
             time_str: now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
             date: now.toLocaleDateString(),
             updated_at: now.toISOString(),
           }, ...prev]);
         }
         break;
       case 'delete':
         // Removed window.confirm because it is blocked in iframe environment
         const success = await movieService.delete(movie.id);
         if (success) {
           if (selectedMovie && selectedMovie.id === movie.id) {
               closeOverlay();
               setSelectedMovie(null);
           }
           toast.success(`档案《${movie.title}》已销毁。`);
           window.dispatchEvent(new CustomEvent('library-list-dirty'));
         } else {
           toast.error("档案销毁任务失败，请检查数据库权限。");
         }
         break;
    }
  };

  // v3：PC 模式下播放页改成 Rust 原生窗口（src-tauri/native_player）。
  // 用户在详情页点「播放」时，前端不再切换到 player overlay；而是
  // 解析出 stream URL + startTime 直接 invoke open_pc_player，原生窗口
  // 关闭后回到详情页并刷新历史。Web 模式仍然用 React Player overlay。
  const isPcRuntime = platform().kind === 'pc';
  const isAndroidRuntime = platform().kind === 'android';

  const storageSourceNeedsReauthorization = (source?: StorageSource | null) => {
    const reason = String(source?.health?.reason || '').toLowerCase();
    return Boolean(source?.requires_reauthorization) || reason === 'auth_expired';
  };

  const openStorageReauthorizationSettings = () => {
    setProfileInitialTab('RESOURCES');
    setCurrentView('profile');
    setOverlayView('none');
    setTimeout(() => {
      if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0;
    }, 0);
  };

  const getAndroidPlaybackCatalog = async (
    movie: Movie, preloadedGroups?: MovieResourceGroups | null,
  ): Promise<AndroidPlaybackCatalog> => {
    const fallback = preloadedGroups?.items?.length ? preloadedGroups : null;
    const groups = await withTimeout(movieService.getResources(String(movie.id)), 2500, fallback)
      .catch(() => fallback);
    const resources = groups?.items?.length ? groups.items : ((movie.resources || []) as unknown as Resource[]);
    const availableIds = new Set(resources.map(resource => resource.id));
    const indexed = (groups?.groups?.seasons || []).map(group => ({
      season: Number(group.season),
      displayTitle: group.display_title || (Number(group.season) === 0 ? '特别篇' : `第 ${group.season} 季`),
      resourceIds: (group.resource_ids || []).filter(id => availableIds.has(id)),
    })).filter(group => Number.isInteger(group.season) && group.season >= 0 && group.resourceIds.length > 0);
    if (indexed.length) return { resources, seasons: indexed };
    const inferred = new Map<number, string[]>();
    resources.forEach(resource => {
      const raw = resource.season ?? resource.resource_info?.display?.season;
      if (raw == null) return;
      const season = Number(raw);
      if (!Number.isInteger(season) || season < 0) return;
      inferred.set(season, [...(inferred.get(season) || []), resource.id]);
    });
    return { resources, seasons: Array.from(inferred.entries()).sort(([a], [b]) => a - b)
      .map(([season, resourceIds]) => ({ season, resourceIds, displayTitle: season === 0 ? '特别篇' : `第 ${season} 季` })) };
  };

  const blockPlayIfStorageAuthExpired = async (
    movie: Movie, options: PlayOptions = {}, preloadedResources?: Resource[],
    sourcesRequest?: Promise<StorageSource[]>,
  ) => {
    const playResources = preloadedResources ?? (await getAndroidPlaybackCatalog(movie)).resources;

    const targetResource = options.resourceId
      ? playResources.find((r) => r.id === options.resourceId)
      : playResources[0];
    const sourceId = targetResource?.source_id;
    if (!sourceId) return false;

    try {
      const sources = await withTimeout(sourcesRequest || storageService.getSources({ includeHealth: true }), 1500, []);
      const source = sources.find((s) => Number(s.id) === Number(sourceId));
      if (!storageSourceNeedsReauthorization(source)) return false;
      const sourceLabel = source?.name || source?.display_name || '光鸭云盘';
      toast.error(`「${sourceLabel}」登录已过期，请在设置的「资源接入与挂载」中重新授权。`, 8000);
      openStorageReauthorizationSettings();
      return true;
    } catch {
      return false;
    }
  };

  const resolveAndroidNativeUrl = (value: string): string => {
    if (!value) return '';
    const apiOrigin = getApiBase().replace(/\/api\/?$/, '');
    if (/^https?:\/\//i.test(value)) {
      try {
        const parsed = new URL(value);
        if (parsed.pathname.startsWith('/api/v1/')) {
          return `${apiOrigin}${parsed.pathname}${parsed.search}`;
        }
      } catch {
        // Malformed values fall through; Media3 will surface a useful error.
      }
      return value;
    }
    if (value.startsWith('/api/')) return `${apiOrigin}${value}`;
    if (value.startsWith('/v1/')) return `${getApiBase().replace(/\/+$/, '')}${value}`;
    if (value.startsWith('/')) return `${apiOrigin}${value}`;
    return value;
  };

  const resolveAndroidArtworkUrl = (value: string | undefined, ticket: string | null): string | undefined => {
    if (!value) return undefined;
    const resolved = resolveAndroidNativeUrl(resolveAssetUrl(value) || value);
    try {
      const backendOrigin = new URL(getApiBase()).origin;
      if (new URL(resolved).origin === backendOrigin) {
        return appendTicket(resolved, ticket);
      }
    } catch {
      // Keep external/CDN artwork usable even if it is not a fully qualified URL.
    }
    return resolved;
  };

  const createAndroidPlaybackSession = async (
    movie: Movie,
    options: PlayOptions,
    preloadedCatalog?: AndroidPlaybackCatalog,
    preloadedTicket?: string | null,
  ) => {
    const catalog = preloadedCatalog ?? await getAndroidPlaybackCatalog(movie);
    const resources = catalog.resources;
    if (resources.length === 0) return null;

    const ticket = preloadedTicket !== undefined ? preloadedTicket : await ensureTicket();
    const contentTypeHints = resources.map((resource) => {
      const info = (resource as any).resource_info || {};
      return String(
        info?.metadata?.edit_context?.media_type_hint
        || info?.metadata?.trace?.media_type_hint
        || '',
      ).trim().toLowerCase();
    });
    const normalizedMovieType = String(movie.type || '').trim().toLowerCase();
    const hasEpisodeMetadata = resources.some((resource) => {
      const info = (resource as any).resource_info || {};
      return info?.display?.episode != null || resource.episode != null;
    });
    const explicitlyMovie = contentTypeHints.includes('movie')
      || resources.some((resource) => Boolean((resource as any).resource_info?.technical?.flag_is_movie_feature))
      || ['movie', 'film', '电影'].includes(normalizedMovieType);
    const explicitlySeries = contentTypeHints.some((hint) => ['tv', 'series', 'show'].includes(hint))
      || ['tv', 'series', 'show', '剧集', '电视剧'].includes(normalizedMovieType);
    // Multiple files alone do not make a series: alternate movie sources stay
    // grouped as one movie unless season/episode metadata says otherwise.
    const contentKind: 'movie' | 'series' = !explicitlyMovie && (
      explicitlySeries
      || movie.has_multi_season_content === true
      || movie.recommendation_card_type === 'season'
      || catalog.seasons.length > 0
      || (movie.target_season != null && hasEpisodeMetadata)
      || hasEpisodeMetadata
    ) ? 'series' : 'movie';
    const subtitleMimeType = (format: string, fallback?: string): string | undefined => {
      switch (format.trim().toLowerCase()) {
        case 'vtt':
          return 'text/vtt';
        case 'srt':
          return 'application/x-subrip';
        case 'ass':
        case 'ssa':
          return 'text/x-ssa';
        default:
          return fallback?.split(';', 1)[0]?.trim() || undefined;
      }
    };
    const toSubtitle = (resource: Resource) => {
      const raw = resource.playback?.subtitles?.items || [];
      const defaultSubtitleId = String(resource.playback?.subtitles?.default_subtitle_id || '');
      return raw.map((item) => {
        const value = item as any;
        const id = String(value.id || value.subtitle_id || '');
        const format = String(value.web_player?.format || value.format || '').toLowerCase();
        const sourceUrl = String(
          value.web_player?.url
          || value.web_player?.stream_url
          || value.url
          || value.stream_url
          || '',
        );
        return {
          id,
          label: value.display_name || value.label || value.match || value.filename || undefined,
          language: typeof value.language === 'string'
            ? value.language
            : value.language?.label || value.language?.name || value.language?.code || undefined,
          format,
          // web_player.url may be an on-the-fly VTT conversion of an SRT/ASS
          // source. Its declared format must win over the original file MIME.
          mimeType: subtitleMimeType(format, value.web_player?.mime_type || value.mime_type),
          url: appendTicket(resolveAndroidNativeUrl(sourceUrl), ticket),
          isDefault: Boolean(value.is_default) || (id && id === defaultSubtitleId),
          isForced: Boolean(value.is_forced) || value.web_player?.kind === 'forced',
          // Media3 can render WebVTT/SRT/ASS text tracks. Bitmap PGS/SUP is
          // intentionally omitted rather than promising unsupported subtitles.
          supported: value.web_player?.supported !== false
            && value.web_player?.native_supported !== false
            && !['sup', 'pgs'].includes(format),
        };
      }).filter((item) => item.id && item.url);
    };

    // Android starts from the original file. Provider cloud transcodes are
    // exposed only as an explicit, lazy-loaded quality choice; CyberStream's
    // server audio/video transcode endpoints never cross this boundary.
    const groupedSeasonByResourceId = new Map<string, number>();
    catalog.seasons.forEach((season) => {
      season.resourceIds.forEach((resourceId) => groupedSeasonByResourceId.set(resourceId, season.season));
    });
    const sessionResources = resources.map((resource) => {
      const handoffHint = resource.playback?.external_player;
      const userAgent = needsUserAgentRewrite(handoffHint)
        ? pickUserAgentForRewrite(handoffHint) || undefined
        : undefined;
      const headers = userAgent ? { 'User-Agent': userAgent } : undefined;

      const info = (resource as any).resource_info || {};
      const rawSeason = Number(
        resource.season
        ?? info?.display?.season
        ?? groupedSeasonByResourceId.get(resource.id),
      );
      const displayTitle = info?.display?.title
        || info?.file?.filename
        || resource.display_label
        || resource.filename
        || `资源 ${resource.id}`;
      const tech = info?.technical || {};
      const filename = String(info?.file?.filename || resource.filename || '').trim() || undefined;
      const storageSource = String(
        info?.file?.storage_source?.name || resource.source_name || '',
      ).trim() || undefined;
      const sizeBytes = Number(resource.size_bytes ?? info?.file?.size_bytes);
      const badges = [
        tech.video_resolution_badge_label || resource.media_info?.resolution,
        tech.video_dynamic_range_label || resource.media_info?.hdr,
        tech.audio_summary_label || tech.audio_codec_label || resource.media_info?.audio_codec,
        tech.source_label,
        ...(Array.isArray(tech.extra_tags) ? tech.extra_tags : []),
      ].map((value) => String(value || '').trim())
        .filter((value, index, values) => value && value.toUpperCase() !== 'UNKNOWN' && values.indexOf(value) === index);
      const cloud = resource.playback?.cloud_transcode;
      const qualitiesEndpoint = cloud?.supported
        ? String(cloud.qualities_endpoint || `/api/v1/resources/${resource.id}/streaming-qualities`)
        : '';
      const streamEndpoint = cloud?.supported
        ? String(cloud.stream_endpoint || `/api/v1/resources/${resource.id}/stream-transcoded`)
        : '';
      const episodeNumber = info?.display?.episode ?? resource.episode;
      const seasonNumber = Number.isInteger(rawSeason) && rawSeason >= 0 ? rawSeason : undefined;
      const episodeSearchSuffix = seasonNumber != null && episodeNumber != null
        ? ` S${String(seasonNumber).padStart(2, '0')}E${String(episodeNumber).padStart(2, '0')}`
        : '';
      const onlineSubtitleBase = `${getApiBase()}/v1/resources/${resource.id}/subtitles/online`;
      return {
        id: resource.id,
        title: displayTitle,
        episode: info?.display?.episode != null
          ? String(info.display.episode)
          : resource.episode != null
          ? String(resource.episode)
          : undefined,
        season: seasonNumber,
        direct: {
          id: 'direct',
          label: '原文件',
          url: appendTicket(movieService.getStreamUrl(resource.id), ticket),
          mimeType: resource.playback?.mime_type,
          userAgent,
          headers,
        },
        subtitles: toSubtitle(resource),
        onlineSubtitles: ticket ? {
          searchUrl: appendTicket(`${onlineSubtitleBase}/search`, ticket),
          downloadUrl: appendTicket(`${onlineSubtitleBase}/download`, ticket),
          bindUrl: appendTicket(`${onlineSubtitleBase}/bind`, ticket),
          apiBaseUrl: getApiBase(),
          defaultKeyword: `${movie.title || ''}${episodeSearchSuffix}`.trim() || undefined,
          providers: ['subhd', 'srtku'],
          // Phone/tablet panels stay useful without rendering up to 100 rows.
          // This remains per-provider, so both sources can still contribute.
          limit: 20,
        } : undefined,
        technical: {
          filename,
          sizeBytes: Number.isFinite(sizeBytes) && sizeBytes > 0 ? sizeBytes : undefined,
          storageSource,
          container: String(info?.file?.container || resource.container || '').trim() || undefined,
          badges: badges.length > 0 ? badges : undefined,
          videoResolution: String(tech.video_resolution_label || resource.media_info?.resolution || '').trim() || undefined,
          videoCodec: String(tech.video_codec_label || resource.media_info?.video_codec || '').trim() || undefined,
          dynamicRange: String(tech.video_dynamic_range_label || resource.media_info?.hdr || '').trim() || undefined,
          bitDepth: String(tech.video_bit_depth_label || '').trim() || undefined,
          audioCodec: String(tech.audio_codec_label || resource.media_info?.audio_codec || '').trim() || undefined,
          audioChannels: String(tech.audio_channels_label || '').trim() || undefined,
          audioSummary: String(tech.audio_summary_label || '').trim() || undefined,
          sourceLabel: String(tech.source_label || '').trim() || undefined,
          qualityTier: String(tech.quality_tier_label || '').trim() || undefined,
        },
        cloudTranscode: cloud?.supported && qualitiesEndpoint && streamEndpoint ? {
          supported: true as const,
          provider: cloud.provider || undefined,
          providerName: cloud.provider_name || undefined,
          qualitiesUrl: appendTicket(resolveAndroidNativeUrl(qualitiesEndpoint), ticket),
          streamUrl: appendTicket(resolveAndroidNativeUrl(streamEndpoint), ticket),
          resolutionParam: cloud.resolution_param || 'resolution',
        } : undefined,
      };
    });

    const initialResourceId = options.resourceId
      && sessionResources.some((resource) => resource.id === options.resourceId)
      ? options.resourceId
      : sessionResources[0].id;
    // The mobile-data confirmation mirrors the detail page: prefer its wide
    // backdrop and only fall back to portrait artwork when no backdrop exists.
    const playbackArtworkCandidate = [
      movie.backdrop_asset_url,
      ...(movie.backdrop_asset_fallback_urls || []),
      movie.backdrop_url,
      movie.poster_asset_url,
      ...(movie.poster_asset_fallback_urls || []),
      movie.poster_url,
      movie.cover_url,
    ].find((value): value is string => typeof value === 'string' && value.trim().length > 0);
    return {
      version: 2 as const,
      sessionId: `android-${crypto.randomUUID()}`,
      initialResourceId,
      startTimeMs: Math.max(0, Number(options.startTime) || 0) * 1000,
      contentKind,
      movie: {
        id: String(movie.id),
        title: movie.title || '',
        posterUrl: resolveAndroidArtworkUrl(playbackArtworkCandidate, ticket),
        seasons: catalog.seasons.length > 0 ? catalog.seasons : undefined,
      },
      resources: sessionResources,
    };
  };

  const launchAndroidPlayback = async (
    movie: Movie,
    options: PlayOptions,
    retried = false,
    preloadedCatalog?: AndroidPlaybackCatalog,
    preloadedTicket?: string | null,
  ): Promise<void> => {
    try {
      const session = await createAndroidPlaybackSession(
        movie,
        options,
        preloadedCatalog,
        preloadedTicket,
      );
      if (!session) {
        toast.error('该影片没有可播放的资源');
        return;
      }
      const result = await launchAndroidPlayer(session);
      if (result.authExpired) {
        invalidateTicket();
        if (!retried) {
          await launchAndroidPlayback(movie, {
            ...options,
            resourceId: result.resourceId || session.initialResourceId,
            startTime: Math.max(0, Number(result.positionMs || 0) / 1000),
          }, true, preloadedCatalog);
        } else {
          // A fresh ticket was rejected too. Do not silently return to the
          // detail page or open the Web player with the same invalid session.
          toast.error('播放授权已失效，请重新登录后重试');
        }
        return;
      }
      if (result.resourceId && (result.positionMs || 0) >= 5_000 && (result.durationMs || 0) > 0) {
        await userService.reportHistory(
          result.resourceId,
          Number(result.positionMs) / 1000,
          Number(result.durationMs) / 1000,
          result.sessionId || session.sessionId,
        );
      }
      if (result.error && !result.authExpired) {
        toast.error(`本机无法解码该原始文件（${result.error}），未启用服务器转码`);
        return;
      }
      refreshHistory();
    } catch (error) {
      console.warn('[android] native player launch failed', error);
      toast.error('原生播放器启动失败；Android 端不会改用网页播放器或服务器转码');
    }
  };

  const handlePlay = async (movie: Movie, options: PlayOptions = {}, preloadedGroups?: MovieResourceGroups | null) => {
    if (isAndroidRuntime) {
      // The Capacitor Activity callback supports only one outstanding call.
      // Lock before any preflight awaits so a double tap cannot race a second
      // player Activity into existence.
      if (androidPlaybackBusyRef.current) return;
      androidPlaybackBusyRef.current = true;
      try {
        const sourcesRequest = storageService.getSources({ includeHealth: true }).catch(() => []);
        const detailRequest = movie.backdrop_asset_url || movie.backdrop_url
          ? Promise.resolve(null) : withTimeout(movieService.getDetail(movie.id), 1500, null).catch(() => null);
        const [detail, catalog, ticket] = await Promise.all([
          detailRequest, getAndroidPlaybackCatalog(movie, preloadedGroups), ensureTicket(),
        ]);
        const playbackMovie = detail ? { ...movie, ...detail, target_season: movie.target_season } : movie;
        if (catalog.resources.length === 0) {
          toast.error('该影片没有可播放的资源');
          return;
        }
        if (await blockPlayIfStorageAuthExpired(movie, options, catalog.resources, sourcesRequest)) return;
        await launchAndroidPlayback(playbackMovie, options, false, catalog, ticket);
      } finally {
        androidPlaybackBusyRef.current = false;
      }
      return;
    }
    if (await blockPlayIfStorageAuthExpired(movie, options)) {
      return;
    }
    if (!isPcRuntime) {
      setPlayOptions(options);
      setOverlayView('player');
      return;
    }
    // PC：单独走 getResources 接口拿到所有可播放资源（movie.resources
    // 在某些列表场景下没有，详情页加载后才有 — 走 API 更稳）。然后把
    // 所有 resource 拍扁成 NativeResourceMeta + 当前 id 一起送给 Rust。
    let resources: import('./types').Resource[] = [];
    let seasonsMeta: { season: number; displayTitle: string; resourceIds: string[] }[] = [];
    try {
      const groups = await movieService.getResources(String(movie.id));
      resources = (groups?.items || []) as import('./types').Resource[];
      // groups.groups.seasons[] 是后端给的"分季索引"。转成 NativeSeasonMeta
      // 形态：每个 season 含 season 编号 / display_title / resource_ids。
      // Rust 拿到后渲染顶部 「第 1 季 / 第 2 季」 tab，并按 resourceIds 过滤
      // 集数网格。空数组就走单季 fallback。
      const rawSeasons = groups?.groups?.seasons || [];
      seasonsMeta = rawSeasons
        .filter(sg => sg.resource_ids && sg.resource_ids.length > 0)
        .map(sg => ({
          season: sg.season,
          displayTitle: sg.display_title || `第 ${sg.season} 季`,
          resourceIds: sg.resource_ids,
        }));
    } catch {
      resources = [];
    }
    if (resources.length === 0) {
      // 兜底：detail 页可能已经把 resources 塞 movie 上
      resources = ((movie.resources || []) as unknown as import('./types').Resource[]);
    }
    if (resources.length === 0) {
      toast.error('该影片没有可播放的资源');
      return;
    }
    const currentResourceId = options.resourceId
      ?? resources[0]?.id
      ?? String(movie.id);
    const startTime = Number(options.startTime) || 0;
    const ticket = await ensureTicket();
    if (!ticket) {
      const status = await authService.getStatus();
      if (!status || status.user_management_enabled) {
        toast.error('无法取得播放授权，请检查后端连接或重新登录。');
        return;
      }
    }
    // 首帧 loadfile 用的 URL：一律用原始 /stream。夸克/UC 现在也是 download
    // 原文件链路，原始 URL 就能直接播且画质最高；清晰度切换由 HUD 菜单接管。
    const url = appendTicket(movieService.getStreamUrl(currentResourceId), ticket);

    // 把每条 resource 拍扁成 NativeResourceMeta：附带直链、画质标签、
    // 大小、画质 badge。badge 由 media_info / resource_info.technical
    // 拼接 — 命中其中之一即填，避免空标签干扰视觉。
    //
    // episode 抽取顺序（与 web Player.tsx 405–435 行一致）：
    //   1. resource_info.display.episode（后端解析好的优先）
    //   2. r.episode 顶层
    //   3. filename 正则（S01E02 / 第X话 / EpXX / 末尾数字）
    const extractEpisode = (r: import('./types').Resource): string | undefined => {
      const info = (r as any).resource_info || {};
      let n: number | string | undefined =
        info?.display?.episode ?? r.episode;
      if (n != null && n !== '') return String(n);
      // 后端明确标了"电影正片"或 media_type_hint = movie 时直接返回 undefined。
      // filename 兜底正则会把 [106.24GB] 这种文件大小标签当成集号抠出来，
      // 导致单部电影被分成"正片 / 106"两个 tab（filename 里凡有方括号
      // 数字都会触发，包括 [www.xxx][1080p] 这类站点 / 画质标签）。
      const tech = info?.technical || {};
      const editCtx = info?.metadata?.edit_context || {};
      if (tech.flag_is_movie_feature || editCtx.media_type_hint === 'movie') {
        return undefined;
      }
      const fn: string = info?.file?.filename || r.filename || '';
      const reSxE = fn.match(/[Ss](\d+)[Ee](\d+)/);
      if (reSxE) return reSxE[2];
      const reSeasonEp = fn.match(/Season\s*\d+\s*Episode\s*(\d+)/i);
      if (reSeasonEp) return reSeasonEp[1];
      const reZh = fn.match(/第\s*(\d+)\s*[集话]/);
      if (reZh) return reZh[1];
      const reEp = fn.match(/(?:^|[^\w])(?:EP|Ep|ep|E|e)(?:\s*[-.]*\s*)?(\d+)/);
      if (reEp) return reEp[1];
      // 括号集号 (1) / （1）—— 国内站点常见命名 tang...S03 (1).mkv。
      // 放在裸数字兜底之前，半角全角都收。
      const reParen = fn.match(/[(（]\s*(\d{1,3})\s*[)）]/);
      if (reParen) return reParen[1];
      const reBare = fn.match(/(?:^|\s|-|\[)\s*(\d{1,3})(?:\s|-|\.|\]|$)/);
      if (reBare) return reBare[1];
      return undefined;
    };
    const nativeResources = await Promise.all(resources.map(async r => {
      const tech = (r as any).resource_info?.technical || {};
      const info: any = (r as any).resource_info || {};
      // displayLabel 优先级和 web Player 行 1936 保持一致：
      //   resource_info.display.title → resource_info.file.filename → r.filename
      // r.display_label / r.filename 后端有时给空字符串，要 .filter(!empty)。
      const displayLabel: string | undefined =
        (info?.display?.title && String(info.display.title).trim()) ||
        (info?.file?.filename && String(info.file.filename).trim()) ||
        (r.display_label && String(r.display_label).trim()) ||
        (r.filename && String(r.filename).trim()) ||
        undefined;
      // storage_source.name → "bilibili" / "115 网盘" 这种 badge，渲染成
      // 大色块和源 badge 区分开（web 行 1931-1933）。
      const storageSource: string | undefined =
        info?.file?.storage_source?.name || undefined;
      // 文件大小：r.size_bytes 顶层 / resource_info.file.size_bytes 都可能填。
      const sizeBytes: number | undefined =
        r.size_bytes || info?.file?.size_bytes || undefined;
      const badges: string[] = [];
      const push = (v?: string | null) => {
        if (v && v.toUpperCase() !== 'UNKNOWN') badges.push(v);
      };
      push(tech.video_resolution_badge_label || r.media_info?.resolution);
      push(tech.video_dynamic_range_label);
      // 视频编码（HEVC/AVC）对用户决策无价值，原生播放器 badge 不再展示，
      // 与详情页顶部技术规格行保持一致。
      push(tech.audio_summary_label || tech.audio_codec_label || r.media_info?.audio_codec);
      push(tech.source_label);
      // 额外标签 (IMAX / Director's Cut 等)：详情页顶部规格行已展示；
      // 原生播放器右侧也补上，跟外面一致。
      if (Array.isArray(tech.extra_tags)) {
        tech.extra_tags.forEach((t: string) => push(t));
      }
      // 字幕：后端 resource_info.playback.subtitles 形态多变——
      //   - 老接口偶尔是 { items: [...] } 包裹
      //   - 新接口直接 array
      //   - 没字幕时可能是 null / undefined / {}
      // 统一拍成 array 再 map，否则 .map() 在对象上会 throw。
      const rawCandidate: any =
        info?.playback?.subtitles
        ?? (r as any).playback?.subtitles
        ?? (r as any).subtitles
        ?? [];
      const subtitlesRaw: any[] = Array.isArray(rawCandidate)
        ? rawCandidate
        : Array.isArray(rawCandidate?.items)
        ? rawCandidate.items
        : [];
      // mpv 在 native 进程里 sub-add 必须能直接 GET 到字幕文件，
      // 后端给的 url 形态有三种：
      //   - 相对路径 `/api/v1/...` 或 `/v1/...`：webview 自己拼 origin 没问题，
      //     丢给 Rust 后 mpv 不带 host 会拒，这里要拼成 `${apiBaseHost}/api/v1/...`
      //   - 绝对 URL 命中 /api/v1/... 路径：后端在反代后面时可能 scheme 错（实际
      //     对外 https，Flask 内部 http），URL 直接交给 mpv 会因 scheme 不一致
      //     连不上。这种情况只取 pathname+search，丢弃 origin，跟当前 apiBaseHost
      //     重新拼。仅本后端 /api/v1/ 路径处理；CDN / 外部 URL 原样返回。
      //   - 其他非 / 开头的奇怪输入：原样返回不动。
      // 注意走 getApiBase()，让用户在「系统配置 → 后端服务器」改的 URL 立即生效
      // （走 platform.getApiBase()，PC 端会读 localStorage 里的 cyber_pc_api_base）。
      const resolveSubUrl = (u: string): string => {
        return resolveAssetUrl(u) || '';
      };
      const subtitles = subtitlesRaw
        .map((s: any) => ({
          id: String(s.id ?? s.subtitle_id ?? ''),
          url: appendTicket(resolveSubUrl(String(s.url ?? s.stream_url ?? '')), ticket),
          label: s.label || s.match || s.filename || undefined,
          displayName: s.display_name || undefined,
          format: s.format || undefined,
          isDefault: !!s.is_default,
          language: typeof s.language === 'string'
            ? s.language : (s.language?.label || s.language?.name || s.language?.code || undefined),
          source: s.source || undefined,
          providerName: s.online?.provider_name || s.online?.provider_id || undefined,
          webPlayerSupported: s.web_player?.supported,
        }))
        .filter((s) => s.id && s.url);
      // 云端转码画质：凡 cloud_transcode.supported（夸克/UC/阿里等，按字段不按
      // 网盘名）就拉一次 streaming-qualities，把 available 档位拍扁成 qualities[]，
      // 让 HUD 画清晰度切换菜单。不支持的资源跳过、零额外请求。失败时 qualities
      // 为空，HUD 不显示菜单，走原始 url（PC 首帧本就默认原文件）。
      let qualities: import('./platform/nativePlayer').NativeQualityMeta[] | undefined;
      if (r.playback?.cloud_transcode?.supported) {
        try {
          const q = await resourceService.getStreamingQualities(r.id);
          const items = (q?.items || []).filter((it) => it.available);
          if (items.length > 0) {
            qualities = items.map((it) => ({
              resolution: it.resolution,
              label: it.label,
              url: appendTicket(resourceService.getTranscodedStreamUrl(r.id, it.resolution), ticket),
              isDefault: it.resolution === q?.default_resolution,
            }));
          }
        } catch {
          /* 拉取失败：qualities 留 undefined，HUD 不画菜单，走原始 url */
        }
      }
      return {
        id: r.id,
        url: appendTicket(movieService.getStreamUrl(r.id), ticket),
        filename: r.filename,
        displayLabel,
        qualityLabel: r.quality_label,
        sizeBytes,
        storageSource,
        episode: extractEpisode(r),
        season: r.season,
        badges,
        subtitles,
        qualities,
      };
    }));

    // 夸克/UC 资源：后端 1.21 起把挂载固定为 download 原文件链路，/stream 就是
    // 可直接播放的原始文件（画质最高、不经转码、不耗 provider 转码资源），是 PC
    // 的首选入口。所以首帧直接用原始 url，不再覆盖成转码档。清晰度切换仍保留——
    // qualities 已塞进 nativeResources，HUD 清晰度菜单让用户按需切到转码档。

    launchNativePlayer({
      url,
      startTime,
      currentResourceId,
      // 百度网盘上游 d.pcs.baidu.com 直链对 UA 敏感（普通播放器 UA 会被反爬挡掉）。
      // 后端 stream URL 走 302 跳到上游，UA 由播放方决定，所以这里要在 mpv
      // 请求 header 里塞百度专用 UA。判定信号来自 resource.playback.external_player：
      //   - requires_user_agent_rewrite=true，或
      //   - reason=baidunetdisk_requires_user_agent_rewrite
      headers: (() => {
        const cur = resources.find(r => r.id === currentResourceId) as any;
        const hint = cur?.playback?.external_player ?? null;
        if (!needsUserAgentRewrite(hint)) return [];
        const ua = pickUserAgentForRewrite(hint);
        return ua ? [['User-Agent', ua] as [string, string]] : [];
      })(),
      // device_id + api_base 给 Rust 心跳线程发 /v1/user/history 用。
      // api_base 去掉末尾 `/api`，让 Rust 端按 `/api/v1/...` 拼接。
      // sessionId 前缀 `pc-` 方便后端日志区分 PC 与 web 来源。
      deviceId: getDeviceId(),
      apiBase: getApiBase().replace(/\/api\/?$/, ''),
      sessionId: `pc-${(crypto as any)?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
      playbackTicket: ticket,
      movie: {
        id: String(movie.id),
        title: movie.title || '',
        originalTitle: (movie as any).original_title,
        year: typeof movie.year === 'number' ? movie.year : undefined,
        overview: (movie as any).overview,
        resources: nativeResources,
        seasons: seasonsMeta.length > 0 ? seasonsMeta : undefined,
      },
    })
      .catch((e) => {
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(`原生播放器启动失败: ${msg}`);
      })
      .finally(() => {
        // 不论成功与否，原生窗口关闭后刷新一次历史（M3.5 加上结束态心跳后才完整）
        refreshHistory();
      });
  };

  return (
    <div className="min-h-screen font-sans selection:bg-secondary selection:text-white relative text-white flex overflow-hidden" style={{ backgroundColor: currentTheme.bg }}>
      <style>{getStyles(settings, currentTheme)}</style>

      {/* 启动鉴权探测期间显示一帧 splash，避免主界面闪一下又被 Login 盖掉 */}
      {!authReady && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center" style={{ backgroundColor: currentTheme.bg }}>
          <div className="font-['Orbitron'] tracking-[0.5em] text-xs animate-pulse"
            style={{ color: 'var(--color-primary)', textShadow: '0 0 8px var(--color-primary)' }}>
            INITIALIZING…
          </div>
        </div>
      )}

      {/* 用户管理开启 + 未登录：只渲染 Login，连主体的全局 scanlines/grid 也跳过，
          否则它们会盖在 Login 之上影响交互；scanlines 单独在 Login 内画。 */}
      {authReady && requireLogin && (
        <Login
          themeName={themeName}
          onLoggedIn={(s) => {
            // 调试旁路 ?force_login=1 在登录成功后自动清掉，避免下次刷新又被强制弹回登录页
            if (forceLogin && typeof window !== 'undefined') {
              const url = new URL(window.location.href);
              url.searchParams.delete('force_login');
              window.history.replaceState(null, '', url.toString());
            }
            setAuthStatus(s);
          }}
        />
      )}

      {!requireLogin && (
        <>
          <div className="scanlines pointer-events-none z-[100]"></div>
          <div className="perspective-grid"></div>

      <div ref={scrollContainerRef} className={`flex-1 flex flex-col relative w-full h-screen overflow-y-auto transition-all duration-300`}>
        {overlayView !== 'player' && (
          <Navbar onNavigate={handleNavigate} currentView={currentView} activeLibraryId={activeLibraryId} onSearch={handleSearch} onProfile={() => { setProfileInitialTab('IDENTITY'); setCurrentView('profile'); setOverlayView('none'); setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0; }, 0); }} notifications={notifications} hideLogo={overlayView === 'detail'} />
        )}

        <main className={`flex-1 flex flex-col w-full`}>
          <div style={{ display: overlayView === 'none' ? 'block' : 'none', flex: 1, minHeight: 0 }}>
            {currentView === 'home' && (<Home onMovieSelect={handleMovieSelect} onViewMore={handleViewCategory} onRequestBindStorage={() => { setProfileInitialTab('RESOURCES'); setProfileOpenAddResource(true); setCurrentView('profile'); setOverlayView('none'); setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0; }, 0); }} />)}
            {currentView === 'library' && (<Library onMovieSelect={handleMovieSelect} initialType={settings.homepage?.libraryDefaults?.type || libraryInitialType} initialSort={settings.homepage?.libraryDefaults?.sort || 'update_time'} activeLibraryId={activeLibraryId} onRequestBind={() => { setProfileInitialTab('LIBRARIES'); setCurrentView('profile'); setOverlayView('none'); }} />)}
            {currentView === 'libraries' && (<LibrariesList libraries={libraries} onSelectLibrary={(id) => { setActiveLibraryId(id); setCurrentView('library'); }} onAddLibrary={() => setCurrentView('add_library')} />)}
            {currentView === 'add_library' && (<AddLibraryWizard onCancel={() => setCurrentView('libraries')} onSuccess={() => {
              refreshLibraries();
              setCurrentView('libraries');
            }} />)}
            {currentView === 'leaderboard' && (<Leaderboard onMovieSelect={handleMovieSelect} />)} 
            {currentView === 'history' && (<HistoryPage history={history} onMovieSelect={handleMovieSelect} onClearHistory={handleClearHistory} onDeleteHistoryItem={handleDeleteHistoryItem} />)} 
            {currentView === 'profile' && (<ProfilePage initialTab={profileInitialTab} initialOpenAddResource={profileOpenAddResource} onConsumeOpenAddResource={() => setProfileOpenAddResource(false)} settings={settings} setSettings={setSettings} favorites={favorites} onToggleFavorite={handleToggleFavorite} onMovieSelect={handleMovieSelect} onEditMetadata={setMetadataMovie} currentTheme={themeName} setTheme={setThemeName} libraries={libraries} onRefreshLibraries={refreshLibraries} vaultState={vaultState} onRefreshVaultStatus={refreshVaultStatus} onRefreshFavorites={refreshFavorites} authStatus={authStatus} onLoggedOut={async () => {
              const fresh = await authService.getStatus();
              if (fresh) setAuthStatus(fresh);
              else setAuthStatus(prev => prev ? { ...prev, authenticated: false, user: null, role: null, auth_via: null } : prev);
              setCurrentView('home');
            }} />)}
            {currentView === 'search' && (<SearchResults query={searchQuery} results={searchResults} onMovieSelect={handleMovieSelect} />)} 
            {currentView === 'review' && (<ReviewWorkbench onMovieSelect={handleMovieSelect} onEditMetadata={setMetadataMovie} />)}
          </div>
          
          {overlayView === 'detail' && selectedMovie && (
            <MovieDetail 
              movie={selectedMovie} history={history} onBack={() => {
              setOverlayView('none');
              setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = savedScroll; }, 0);
            }} 
              onPlay={(options = {}, groups) => handlePlay(selectedMovie, options, groups)}
              onMovieSelect={handleMovieSelect} 
              isFavorite={favorites.some(f => f.id === selectedMovie.id)} 
              onToggleFavorite={handleToggleFavorite} 
              onUpdateMovie={(updatedMovie) => {
                setSelectedMovie(updatedMovie);
              }}
            />
          )} 
          
          {overlayView === 'player' && selectedMovie && !isPcRuntime && (
            <Player movie={selectedMovie} initialOptions={playOptions} onBack={() => {
                setOverlayView('detail');
                refreshHistory();
            }} />
          )}
          
          {overlayView !== 'player' && <Footer />} 
        </main>
      </div>

      {/* Global Context Menu */}
      <ContextMenu 
        visible={contextMenu.visible} 
        x={contextMenu.x} 
        y={contextMenu.y} 
        movie={contextMenu.movie} 
        activeLibraryId={currentView === 'library' ? activeLibraryId : null}
        isFavorite={contextMenu.movie ? favorites.some(f => f.id === contextMenu.movie!.id) : false}
        onClose={() => setContextMenu(prev => ({ ...prev, visible: false }))}
        onAction={handleContextMenuAction}
      />

      {/* Add to Library Modal */}
      {addToLibraryMovie && (
        <AddToLibraryModal
          movie={addToLibraryMovie}
          libraries={libraries}
          onClose={() => setAddToLibraryMovie(null)}
          onAdded={() => {
            // Optional: trigger library refresh if we want, but it's okay not to
          }}
        />
      )}

      {/* Global Metadata Editor */}
      {metadataMovie && (
        <MetadataEditor 
          movie={metadataMovie}
          onClose={() => setMetadataMovie(null)}
          onUpdateQuietly={(updatedMovie) => {
            if (selectedMovie && selectedMovie.id === updatedMovie.id) {
              setSelectedMovie(updatedMovie);
            }
          }}
          onSave={(updatedMovie) => {
            setMetadataMovie(null);
            // Also update selectedMovie if it's the one being edited
            if (selectedMovie && selectedMovie.id === updatedMovie.id) {
              setSelectedMovie(updatedMovie);
            }
            window.dispatchEvent(new CustomEvent('movie-updated', { detail: updatedMovie }));
          }}
        />
      )}

      {/* Global TMDB Match Modal */}
      {matchMovie && (
        <TMDBMatchModal
          movieId={String(matchMovie.id)}
          initialQuery={matchMovie.title || ''}
          initialYear={matchMovie.year ? String(matchMovie.year) : ''}
          onClose={() => setMatchMovie(null)}
          onMatch={(updatedMovie) => {
             setMatchMovie(null);
             if (selectedMovie && selectedMovie.id === updatedMovie.id) {
                 setSelectedMovie(updatedMovie);
             }
             toast.success(`《${updatedMovie.title}》元数据匹配已应用`);
             window.dispatchEvent(new CustomEvent('movie-updated', { detail: updatedMovie }));
          }}
        />
      )}

      {/* Global Scan Progress */}
      <ScanProgressBar />
      <BackgroundJobProgressBar />

      {/* Global Notification System */}
      <Toaster />
        </>
      )}
    </div>
  );
};

export default App;
