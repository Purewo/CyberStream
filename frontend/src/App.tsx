import React, { useEffect, useState } from 'react';
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
import { movieService, libraryService, userService, resourceService } from './api';
import { authService, AuthStatus } from './api/auth';
import { Login } from './features/Login';
import { getDeviceId } from './api/core';
import { getPublicUrlBase, writeClipboard, platform, getApiBase } from './platform';
import { launchNativePlayer, needsUserAgentRewrite, pickUserAgentForRewrite } from './platform/nativePlayer';
import { getStyles, toast } from './utils';
import { useGlobalHotkeys } from './hooks/useGlobalHotkeys';
import { Movie, ViewState, PlayOptions } from './types';
import { useThemeSettings } from './hooks/useThemeSettings';
import { useUserData } from './hooks/useUserData';
import { useAppRouting } from './hooks/useAppRouting';
import { TMDBMatchModal } from './features/TMDBMatchModal';

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

  const handlePlay = async (movie: Movie, options: PlayOptions = {}) => {
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
    // 首帧 loadfile 用的 URL：一律用原始 /stream。夸克/UC 现在也是 download
    // 原文件链路，原始 URL 就能直接播且画质最高；清晰度切换由 HUD 菜单接管。
    const url = movieService.getStreamUrl(currentResourceId);

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
      const apiBaseHost = getApiBase().replace(/\/api\/?$/, '');
      const resolveSubUrl = (u: string): string => {
        if (!u) return '';
        if (/^https?:\/\//i.test(u)) {
          try {
            const parsed = new URL(u);
            if (parsed.pathname.startsWith('/api/v1/')) {
              return `${apiBaseHost}${parsed.pathname}${parsed.search}`;
            }
          } catch { /* malformed URL, fall through */ }
          return u;
        }
        if (u.startsWith('/api/')) return `${apiBaseHost}${u.substring(4)}`;
        if (u.startsWith('/v1/')) return `${apiBaseHost}${u}`;
        if (u.startsWith('/')) return `${apiBaseHost}${u}`;
        return u;
      };
      const subtitles = subtitlesRaw
        .map((s: any) => ({
          id: String(s.id ?? s.subtitle_id ?? ''),
          url: resolveSubUrl(String(s.url ?? s.stream_url ?? '')),
          label: s.label || s.match || s.filename || undefined,
          displayName: s.display_name || undefined,
          format: s.format || undefined,
          isDefault: !!s.is_default,
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
              url: resourceService.getTranscodedStreamUrl(r.id, it.resolution),
              isDefault: it.resolution === q?.default_resolution,
            }));
          }
        } catch {
          /* 拉取失败：qualities 留 undefined，HUD 不画菜单，走原始 url */
        }
      }
      return {
        id: r.id,
        url: movieService.getStreamUrl(r.id),
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
              onPlay={(options = {}) => handlePlay(selectedMovie, options)}
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