import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { motion } from 'motion/react';
import { ChevronLeft, Play, Pause, Volume2, VolumeX, Lock, Maximize, BoxSelect, Scan, Activity, LayoutGrid, Server, HardDrive } from 'lucide-react';
import { Movie, PlayOptions, Episode } from '../types';
import { movieService, userService } from '../api';
import { formatDuration } from '../utils';
import { SciFiProgressRing, EcgLoading } from './ui/CyberComponents';
import { API_BASE } from '../constants';

interface PlayerProps {
  movie: Movie;
  onBack: () => void;
  initialOptions: PlayOptions;
}

export const Player: React.FC<PlayerProps> = ({ movie, onBack, initialOptions }) => { 
  const videoRef = useRef<HTMLVideoElement>(null); 
  const audioRef = useRef<HTMLAudioElement>(null);
  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const bufferingRef = useRef<boolean>(false);
  
  const [isPlaying, setIsPlaying] = useState(false); 
  const [currentTime, setCurrentTime] = useState(0); 
  const [duration, setDuration] = useState(0); 
  const [volume, setVolume] = useState(1); 
  const [isLocked, setIsLocked] = useState(false); 
  const [aspectRatio, setAspectRatio] = useState<'contain' | 'cover'>('contain'); 
  const [playbackRate, setPlaybackRate] = useState(1); 
  const [retryCount, setRetryCount] = useState(0);
  const [isDraggingSeek, setIsDraggingSeek] = useState(false);
  const isDraggingSeekRef = useRef(false);
  const [dragSeekTime, setDragSeekTime] = useState(0);
  const [resourceGroups, setResourceGroups] = useState<import('../types').MovieResourceGroups | null>(null);
  const [currentEpisode, setCurrentEpisode] = useState<import('../types').Resource | null>(null); 
  const [loading, setLoading] = useState(true); 
  const [isBuffering, setIsBuffering] = useState(false);
  const [progress, setProgress] = useState(0); 
  const [seekOnLoad, setSeekOnLoad] = useState<number | null>(null); 
  const [playbackMode, setPlaybackMode] = useState<'direct' | 'proxy' | 'audio_transcode'>('direct');
  const [isAudioLoading, setIsAudioLoading] = useState(false);
  
  useEffect(() => {
    if (currentEpisode) {
        if (playbackMode === 'audio_transcode' && !currentEpisode.playback?.audio?.server_transcode?.available) {
            setPlaybackMode('direct');
        }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentEpisode]);
  const [activeSeason, setActiveSeason] = useState<number | 'standalone' | null>(null);
  const [episodePage, setEpisodePage] = useState(0);
  const [showSourceSelector, setShowSourceSelector] = useState(false);
  const [hoveredSourcePath, setHoveredSourcePath] = useState<string | null>(null);
  const [hoveredEpInfo, setHoveredEpInfo] = useState<{ep: string, sources: import('../types').Resource[], rect?: DOMRect} | null>(null);
  const [audioSeekTime, setAudioSeekTime] = useState(0);

  const EPISODES_PER_PAGE = 30;
  
  const tabsWrapperRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const sourceSelectorRef = useRef<HTMLDivElement>(null);
  const [visibleSeasonCount, setVisibleSeasonCount] = useState(0);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
        if (sourceSelectorRef.current && !sourceSelectorRef.current.contains(event.target as Node)) {
            setShowSourceSelector(false);
        }
    };
    
    if (showSourceSelector) {
        document.addEventListener('mousedown', handleClickOutside);
    }
    
    return () => {
        document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showSourceSelector]);


  useEffect(() => { 
    if (!movie) return; 
    setLoading(true); 

    movieService.getResources(movie.id).then(resData => {
      if (resData) {
        setResourceGroups(resData);
        
        let targetRes: import('../types').Resource | undefined;
        if (initialOptions?.resourceId) {
          targetRes = resData.items.find(r => r.id === initialOptions.resourceId);
        }
        
        if (targetRes) {
          setCurrentEpisode(targetRes);
          setIsPlaying(true);
        } else if (resData.items.length > 0) {
          setCurrentEpisode(resData.items[0]);
          setIsPlaying(true);
        }
      }
      setLoading(false);
    });

  }, [movie, initialOptions]); 
  
  useEffect(() => {
    if (resourceGroups && currentEpisode && activeSeason === null) {
       const inSeason = resourceGroups.groups?.seasons?.find(sg => sg.resource_ids.includes(currentEpisode.id));
       if (inSeason) setActiveSeason(inSeason.season);
       else if (resourceGroups.groups?.standalone?.resource_ids.includes(currentEpisode.id)) setActiveSeason('standalone');
       else setActiveSeason('standalone'); // fallback
    }
  }, [currentEpisode, resourceGroups, activeSeason]);

  const playingEpisodeSources = useMemo(() => {
     if (!currentEpisode || !resourceGroups?.groups) return [];
     const cid = currentEpisode.id;
     const inStandalone = resourceGroups.groups.standalone?.resource_ids?.includes(cid);
     
     let poolIds: string[] = [];
     if (inStandalone) {
         poolIds = resourceGroups.groups.standalone.resource_ids;
     } else {
         const seasonGroup = resourceGroups.groups.seasons?.find(sg => sg.resource_ids.includes(cid));
         if (seasonGroup) poolIds = seasonGroup.resource_ids;
     }
     
     let targetEpNum = currentEpisode.resource_info?.display?.episode ?? currentEpisode.episode;
     const targetFilename = currentEpisode.resource_info?.file?.filename || currentEpisode.filename || '';
     if (targetEpNum === undefined || targetEpNum === null) {
         const match2 = targetFilename.match(/第\s*(\d+)\s*[集话]/);
         const match1 = targetFilename.match(/(?:[EePp]|Ep)\s*(\d+)/i);
         const match3 = targetFilename.match(/^(\d+)/);
         if (match2 && match2[1]) targetEpNum = parseInt(match2[1], 10);
         else if (match1 && match1[1]) targetEpNum = parseInt(match1[1], 10);
         else if (match3 && match3[1]) targetEpNum = parseInt(match3[1], 10);
     }
     
     // If we still can't parse an episode...
     if (targetEpNum === undefined || targetEpNum === null || isNaN(targetEpNum)) {
         // Is this a movie (not a TV show)?
         const isMovieContent = movie?.type === 'movie' || movie?.has_multi_season_content === false;
         
         if (isMovieContent || (!movie?.type && inStandalone)) {
             // For movies or purely standalone content, all items in the pool are likely alternative versions/sources
             return poolIds.map(id => resourceGroups.items.find(r => r.id === id)).filter(Boolean) as import('../types').Resource[];
         }
         
         return [currentEpisode];
     }

     return poolIds
         .map(id => resourceGroups.items.find(r => r.id === id))
         .filter(res => {
             if (!res) return false;
             let resEpNum = res.resource_info?.display?.episode ?? res.episode;
             if (resEpNum === undefined || resEpNum === null) {
                 const filename = res.resource_info?.file?.filename || res.filename || '';
                 const matchSxE = filename.match(/[Ss]\d+[Ee](\d+)/);
                 const matchSeasonEp = filename.match(/Season\s*\d+\s*Episode\s*(\d+)/i);
                 const match2 = filename.match(/第\s*(\d+)\s*[集话]/);
                 const match1 = filename.match(/(?:[EePp]|Ep)\s*(\d+)/i);
                 const match3 = filename.match(/(?:^|\s|-)\s*(\d{2,3})(?:\s|-|\.|$)/);
                 if (matchSxE && matchSxE[1]) resEpNum = parseInt(matchSxE[1], 10);
                 else if (matchSeasonEp && matchSeasonEp[1]) resEpNum = parseInt(matchSeasonEp[1], 10);
                 else if (match2 && match2[1]) resEpNum = parseInt(match2[1], 10);
                 else if (match1 && match1[1]) resEpNum = parseInt(match1[1], 10);
                 else if (match3 && match3[1]) resEpNum = parseInt(match3[1], 10);
             }
             return resEpNum === targetEpNum;
         }) as import('../types').Resource[];
  }, [currentEpisode, resourceGroups]);

  const seasonTabs = useMemo(() => {
     if (!resourceGroups) return [];
     
     // Determine the actual playing season
     let playingSeasonValue: number | 'standalone' | null = null;
     if (currentEpisode) {
         const inSeason = resourceGroups.groups?.seasons?.find(sg => sg.resource_ids.includes(currentEpisode.id));
         if (inSeason) playingSeasonValue = inSeason.season;
         else if (resourceGroups.groups?.standalone?.resource_ids.includes(currentEpisode.id)) playingSeasonValue = 'standalone';
     }

     const tabs: { label: string, value: number | 'standalone', isPlaying?: boolean }[] = [];
     
     if (resourceGroups.groups?.standalone?.count > 0) {
         tabs.push({ label: '正片', value: 'standalone', isPlaying: playingSeasonValue === 'standalone' });
     }
     if (resourceGroups.groups?.seasons) {
         resourceGroups.groups.seasons.forEach(sg => {
             tabs.push({ label: sg.display_title || `第 ${sg.season} 季`, value: sg.season, isPlaying: playingSeasonValue === sg.season });
         });
     }
     
     // Move playing season to the front
     if (playingSeasonValue) {
         const activeIndex = tabs.findIndex(t => t.value === playingSeasonValue);
         if (activeIndex > 0) {
             const activeTab = tabs.splice(activeIndex, 1)[0];
             tabs.unshift(activeTab);
         }
     }
     
     return tabs;
  }, [resourceGroups, currentEpisode]);

  const currentSeasonItems = useMemo(() => {
     if (!resourceGroups) return [];
     let items: import('../types').Resource[] = [];
     
     if (activeSeason === 'standalone') {
         items = resourceGroups.groups?.standalone?.resource_ids.map(id => resourceGroups.items.find(r => r.id === id)).filter(Boolean) as import('../types').Resource[] || [];
     } else if (typeof activeSeason === 'number') {
         const sg = resourceGroups.groups?.seasons?.find(s => s.season === activeSeason);
         if (sg) {
             items = sg.resource_ids.map(id => resourceGroups.items.find(r => r.id === id)).filter(Boolean) as import('../types').Resource[];
         }
     }
     return items;
  }, [resourceGroups, activeSeason]);

  useEffect(() => {
    if (!seasonTabs?.length) return;
    setVisibleSeasonCount(seasonTabs.length);
    
    let debounceTimer: ReturnType<typeof setTimeout>;
    
    const observer = new ResizeObserver(() => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        if (!tabsWrapperRef.current || !measureRef.current) return;
        const availableWidth = tabsWrapperRef.current.clientWidth - 32; // 32px for dropdown button
        const children = Array.from(measureRef.current.children) as HTMLElement[];
        
        let currentTotalWidth = 0;
        children.forEach((c, i) => {
            currentTotalWidth += c.offsetWidth + (i > 0 ? 16 : 0);
        });
        
        if (currentTotalWidth <= tabsWrapperRef.current.clientWidth) {
            setVisibleSeasonCount(children.length);
            return;
        }

        let currentWidth = 0;
        let count = 0;
        for (let i = 0; i < children.length; i++) {
            currentWidth += children[i].offsetWidth + (i > 0 ? 16 : 0);
            if (currentWidth > availableWidth) break;
            count++;
        }
        setVisibleSeasonCount(count > 0 ? count : 1);
      }, 50);
    });

    if (tabsWrapperRef.current) {
        observer.observe(tabsWrapperRef.current);
    }
    return () => {
        observer.disconnect();
        clearTimeout(debounceTimer);
    };
  }, [seasonTabs]);

  const episodeGroups = useMemo(() => {
     const groups: Record<string, import('../types').Resource[]> = {};
     let undefinedCount = 0;
     currentSeasonItems.forEach((res) => {
         let epNum = res.resource_info?.display?.episode ?? res.episode;
         
         const filename = res.resource_info?.file?.filename || res.filename || '';
         const isExplicitSeries = movie?.type === 'series' || movie?.type === 'tv' || !!movie?.season || !!movie?.has_multi_season_content || (resourceGroups?.summary?.season_count || 0) > 0;
         const isEffectivelySeries = isExplicitSeries || currentSeasonItems.length > 2;
         const isMovie = !isEffectivelySeries;
         
         if (epNum === undefined || epNum === null) {
             // Standard S01E02 / s1e2
             const matchSxE = filename.match(/[Ss]\d+[Ee](\d+)/);
             // Season 1 Episode 2
             const matchSeasonEp = filename.match(/Season\s*\d+\s*Episode\s*(\d+)/i);
             // Japanese style 第X话
             const match2 = filename.match(/第\s*(\d+)\s*[集话]/);
             // Ep 2 / EP02 / E02 / .E02 / - E02
             const match1 = filename.match(/(?:^|[^\w])(?:EP|Ep|ep|E|e)(?:\s*[-.]*\s*)(\d+)/i) || filename.match(/(?:^|[^\w])(?:EP|Ep|ep|E|e)(\d+)/i);
             // 01.mp4 or - 01 
             const match3 = filename.match(/(?:^|\s|-|\[)\s*(\d{1,3})(?:\s|-|\.|\]|$)/);
             
             if (matchSxE && matchSxE[1]) epNum = parseInt(matchSxE[1], 10);
             else if (matchSeasonEp && matchSeasonEp[1]) epNum = parseInt(matchSeasonEp[1], 10);
             else if (match2 && match2[1]) epNum = parseInt(match2[1], 10);
             else if (match1 && match1[1]) epNum = parseInt(match1[1], 10);
             // Use generic number matcher only if we strongly believe it's a series
             else if (isEffectivelySeries && match3 && match3[1]) epNum = parseInt(match3[1], 10);
         }
         
         let epKey: string;
         if (epNum !== undefined && epNum !== null && !isNaN(epNum)) {
             epKey = epNum.toString();
         } else if (isMovie && currentSeasonItems.length <= 5) {
             epKey = `MOV_FILE_${res.id}`;
         } else {
             const upperFilename = filename.toUpperCase();
             if (upperFilename.includes("PV") || filename.includes("前瞻") || filename.includes("预告") || upperFilename.includes("SPECIAL") || upperFilename.includes("SP")) {
                 epKey = `SP_${String(undefinedCount++).padStart(4, '0')}`;
             } else {
                 epKey = `EXT_${String(undefinedCount++).padStart(4, '0')}`;
             }
         }

         if (!groups[epKey]) groups[epKey] = [];
         groups[epKey].push(res);
     });
     return groups;
  }, [currentSeasonItems]);

  const sortedEpisodeEntries = useMemo(() => {
     return Object.entries(episodeGroups).sort(([a], [b]) => {
         const numA = parseInt(a);
         const numB = parseInt(b);
         if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
         return a.localeCompare(b);
     });
  }, [episodeGroups]);

  const totalEps = sortedEpisodeEntries.length;
  const totalPages = Math.ceil(totalEps / EPISODES_PER_PAGE);

  useEffect(() => {
     setEpisodePage(0);
  }, [activeSeason]);

  useEffect(() => {
     if (currentEpisode && sortedEpisodeEntries.length > 0) {
         const index = sortedEpisodeEntries.findIndex(([_, sources]) => sources.some(s => s.id === currentEpisode.id));
         if (index !== -1) {
             setEpisodePage(Math.floor(index / EPISODES_PER_PAGE));
         }
     }
  }, [currentEpisode, sortedEpisodeEntries, EPISODES_PER_PAGE]);

  const currentEpEntries = totalPages > 1 
     ? sortedEpisodeEntries.slice(episodePage * EPISODES_PER_PAGE, (episodePage + 1) * EPISODES_PER_PAGE) 
     : sortedEpisodeEntries;
  
  useEffect(() => { 
    if (initialOptions?.startTime) { 
      setSeekOnLoad(initialOptions.startTime); 
    } 
  }, [initialOptions]); 
  
  // const needsAudioTranscode = currentEpisode?.playback?.web_player?.needs_server_audio_transcode === true;
  const audioServerTranscode = currentEpisode?.playback?.audio?.server_transcode;
  const isAudioTranscodeActive = playbackMode === 'audio_transcode' && audioServerTranscode?.available === true && !!currentEpisode?.id;

  useEffect(() => {
    sessionIdRef.current = crypto.randomUUID();
    setAudioSeekTime(0);
    
    return () => {
      if (currentEpisode?.id) {
         const prefix = API_BASE.replace(/\/$/, '');
         fetch(`${prefix}/v1/resources/${currentEpisode.id}/audio-transcode?session_id=${encodeURIComponent(sessionIdRef.current)}`, {
           method: 'DELETE',
           keepalive: true
         }).catch(e => console.warn("Failed to delete audio transcode session", e));
      }
    };
  }, [currentEpisode?.id]);

  const lastReportedTimeRef = useRef<number>(0);
  const lastReportedPosRef = useRef<number>(-1);
  const reportProgressRef = useRef<() => void>();

  useEffect(() => { 
    reportProgressRef.current = () => {
      if (videoRef.current && currentEpisode?.id) { 
        const currentTime = videoRef.current.currentTime;
        const dur = videoRef.current.duration;
        const now = Date.now();
        
        if (currentTime > 5 && (now - lastReportedTimeRef.current > 3000)) {
          if (Math.abs(currentTime - lastReportedPosRef.current) >= 1) {
            lastReportedTimeRef.current = now;
            lastReportedPosRef.current = currentTime;
            const safeDuration = (Number.isFinite(dur) && !isNaN(dur)) ? dur : 0;
            userService.reportHistory(currentEpisode.id, currentTime, safeDuration, sessionIdRef.current); 
          }
        }
      } 
    };
  });

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (isPlaying) {
      interval = setInterval(() => {
         reportProgressRef.current?.();
      }, 10000); 
    }
    return () => {
      if (interval) clearInterval(interval);
    }; 
  }, [isPlaying]); 

  // Report progress when unmounting or changing episodes
  useEffect(() => {
    return () => {
       reportProgressRef.current?.();
    };
  }, [currentEpisode?.id]);

  // URL construction
  const videoUrl = useMemo(() => {
    if (!currentEpisode?.id) return "";
    let url = movieService.getStreamUrl(currentEpisode.id);
    if (playbackMode === 'proxy') {
        // Not supported yet, placeholder
    }
    return url;
  }, [currentEpisode, playbackMode]);

  useEffect(() => {
    setRetryCount(0);
  }, [videoUrl]);

  const buildAudioTranscodeUrl = useCallback((currentTime: number) => {
     if (!audioServerTranscode || !audioServerTranscode.endpoint || !currentEpisode?.id) return '';
     let path = audioServerTranscode.endpoint.replace('{id}', currentEpisode.id);
     
     let fullPath = '';
     if (path.startsWith('http://') || path.startsWith('https://')) {
         fullPath = path;
     } else {
         let prefix = API_BASE.replace(/\/$/, '');
         if (prefix.endsWith('/api') && path.startsWith('/api/')) {
             path = path.substring(4);
         }
         fullPath = `${prefix}${path.startsWith('/') ? '' : '/'}${path}`;
     }
     
     try {
         const url = new URL(fullPath, window.location.origin);
         url.searchParams.set("start", Math.max(0, currentTime || 0).toFixed(3));
         url.searchParams.set("audio_track", "0");
         url.searchParams.set("format", "mp3");
         url.searchParams.set("session_id", sessionIdRef.current);
         return url.toString();
     } catch (e) {
         console.warn("Invalid URL construction:", e);
         return '';
     }
  }, [audioServerTranscode, currentEpisode?.id]);

  const loadAudioStream = useCallback(() => {
      const v = videoRef.current;
      const a = audioRef.current;
      if (!v || !a || !isAudioTranscodeActive) return;
      
      setIsAudioLoading(true);
      v.pause();
      // Keep isPlaying state unchanged
      
      a.pause();
      a.removeAttribute('src');
      a.load();
      
      const currentVideoTime = v.currentTime;
      const endpoint = buildAudioTranscodeUrl(currentVideoTime);
      if (endpoint) {
          setAudioSeekTime(currentVideoTime);
          a.src = endpoint;
          a.play().catch(console.warn);
      }
  }, [isAudioTranscodeActive, buildAudioTranscodeUrl]);

  const syncAudioStream = useCallback(() => {
      const v = videoRef.current;
      const a = audioRef.current;
      if (!v || !a) return;
      
      const targetVideoTime = v.currentTime;
      const targetAudioTime = targetVideoTime - audioSeekTime;
      
      let isBuffered = false;
      if (targetAudioTime >= 0) {
          for (let i = 0; i < a.buffered.length; i++) {
              // 允许更宽的误差寻找 buffered
              if (targetAudioTime >= a.buffered.start(i) && targetAudioTime <= a.buffered.end(i) + 5) {
                  isBuffered = true;
                  break;
              }
          }
      }

      if (isBuffered) {
          a.currentTime = targetAudioTime;
          setIsAudioLoading(false);
          const shouldPlay = draggedPlayStateRef.current !== null ? draggedPlayStateRef.current : isPlaying;
          if (shouldPlay && !bufferingRef.current) {
              v.play().catch(console.warn);
              a.play().catch(console.warn);
          } else if (shouldPlay && bufferingRef.current) {
              // Just align the audio, leave the playback paused for buffer
          }
          draggedPlayStateRef.current = null;
      } else {
          loadAudioStream();
      }
  }, [audioSeekTime, isPlaying, loadAudioStream]);

  const seekTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const handleSeeked = useCallback(() => {
     if (isAudioTranscodeActive) {
         if (seekTimeoutRef.current) clearTimeout(seekTimeoutRef.current);
         seekTimeoutRef.current = setTimeout(() => {
             syncAudioStream();
         }, 100);
     }
  }, [isAudioTranscodeActive, syncAudioStream]);

  useEffect(() => {
      if (isAudioTranscodeActive) {
          loadAudioStream();
      }
  }, [isAudioTranscodeActive, loadAudioStream]);

  const handleShowDiagnostics = async () => {
    if (!currentEpisode?.id) return;
    try {
        const prefix = API_BASE.replace(/\/$/, '');
        const res = await fetch(`${prefix}/v1/resources/${currentEpisode.id}/audio-transcode/diagnostics?session_id=${encodeURIComponent(sessionIdRef.current)}`);
        const data = await res.json();
        console.log('Audio Transcode Diagnostics:', data);
        alert(JSON.stringify(data.data || data, null, 2));
    } catch (e) {
        console.error('Failed to get diagnostics:', e);
        alert('Failed to get diagnostics: ' + String(e));
    }
  };

  const handleEpisodeChange = (res: import('../types').Resource) => { 
    setCurrentEpisode(res); 
    setIsPlaying(true); 
  }; 

  const togglePlay = async () => { 
    const v = videoRef.current; 
    const a = audioRef.current;
    if (!v) return; 
    try { 
      if (!isPlaying) { 
        bufferingRef.current = false;
        await v.play(); 
        if (isAudioTranscodeActive && a) a.play().catch(e => console.warn(e));
        setIsPlaying(true);
      } else { 
        v.pause(); 
        if (isAudioTranscodeActive && a) a.pause();
        setIsPlaying(false);
        bufferingRef.current = false;
        setIsBuffering(false);
      } 
    } catch (err) { console.warn("Playback error", err); } 
  }; 

  const onVideoPlay = () => {
     if (videoRef.current && videoRef.current.paused) return;
     if (!bufferingRef.current) setIsPlaying(true);
     if (isAudioTranscodeActive && audioRef.current && !bufferingRef.current) audioRef.current.play().catch(() => {});
  };
  
  const onVideoPause = () => {
     if (videoRef.current && !videoRef.current.paused) return;
     if (!bufferingRef.current && !isDraggingSeekRef.current) setIsPlaying(false);
     if (isAudioTranscodeActive && audioRef.current) audioRef.current.pause();
  };

  const onVideoWaiting = () => {
      setIsBuffering(true);
      if (videoRef.current && isPlaying) {
          if (isAudioTranscodeActive) {
              bufferingRef.current = true;
              videoRef.current.pause();
              if (audioRef.current) audioRef.current.pause();
          }
      }
  };

  const onVideoPlaying = () => {
      setIsBuffering(false);
  };

  useEffect(() => {
     const interval = setInterval(() => {
         const v = videoRef.current;
         if (v && bufferingRef.current && isPlaying) {
             const currentTime = v.currentTime;
             let bufferedAhead = 0;
             for (let i = 0; i < v.buffered.length; i++) {
                 // Allow a small margin (e.g. 0.5s) to catch buffers that start slightly after currentTime
                 if (currentTime >= v.buffered.start(i) - 0.5 && currentTime <= v.buffered.end(i)) {
                     // The end of this buffered range minus current time is how much ahead we have
                     bufferedAhead = Math.max(0, v.buffered.end(i) - currentTime);
                     break;
                 }
             }
             const d = v.duration || 0;
             // 当缓冲达到 5 秒或已经缓冲到了结尾附近，恢复播放。避免一卡一卡。
             if (bufferedAhead >= 5 || currentTime + bufferedAhead >= d - 0.5) {
                 bufferingRef.current = false;
                 setIsBuffering(false);
                 v.play().catch(console.warn);
                 if (isAudioTranscodeActive && audioRef.current) {
                     audioRef.current.play().catch(console.warn);
                 }
             }
         }
     }, 250);
     return () => clearInterval(interval);
  }, [isPlaying, isAudioTranscodeActive]);

  const handleTimeUpdate = () => { 
    if (videoRef.current) { 
      const vTime = videoRef.current.currentTime;
      if (!isDraggingSeek) {
          setCurrentTime(vTime); 
      }
      const d = videoRef.current.duration || 0; 
      setDuration(d); 
      setProgress(d > 0 ? ((isDraggingSeek ? dragSeekTime : vTime) / d) * 100 : 0); 
      
      // Soft Sync Algorithm for external audio
      if (isAudioTranscodeActive && audioRef.current && !audioRef.current.paused) {
          // The audio element's currentTime is relative to the start of the stream fetched
          // So the absolute audio time in the media is audioSeekTime + aTime
          const absoluteAudioTime = audioSeekTime + audioRef.current.currentTime;
          const diff = vTime - absoluteAudioTime;
          
          if (Math.abs(diff) > 0.15 && Math.abs(diff) < 2) {
             const targetRate = diff > 0 ? 1.05 : 0.95;
             if (audioRef.current.playbackRate !== targetRate) {
                 audioRef.current.playbackRate = targetRate;
             }
          } 
          else if (Math.abs(diff) >= 2) {
             // Too far out of sync. Use the full sync logic
             syncAudioStream();
          } 
          else {
             if (audioRef.current.playbackRate !== 1) audioRef.current.playbackRate = 1;
          }
      }
    } 
  }; 

  const draggedPlayStateRef = useRef<boolean | null>(null);

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => { 
    const t = parseFloat(e.target.value); 
    setDragSeekTime(t);
    if (duration > 0) {
        setProgress((t / duration) * 100);
    }
  }; 

  const handleSeekStart = () => {
    isDraggingSeekRef.current = true;
    setIsDraggingSeek(true);
    setDragSeekTime(currentTime);
    if (videoRef.current) {
        if (draggedPlayStateRef.current === null) {
            draggedPlayStateRef.current = isPlaying;
        }
        videoRef.current.pause();
    }
  };

  const handleSeekEnd = () => {
    isDraggingSeekRef.current = false;
    setIsDraggingSeek(false);
    if (videoRef.current) { 
        videoRef.current.currentTime = dragSeekTime; 
        setCurrentTime(dragSeekTime); 
        if (isAudioTranscodeActive) {
            setIsAudioLoading(true);
            videoRef.current.pause();
            // Removed setIsPlaying(false) here to avoid resetting play intention
        } else if (draggedPlayStateRef.current) {
            videoRef.current.play().catch(console.warn);
        }
        draggedPlayStateRef.current = null;
    } 
  }; 

  const changePlaybackRate = () => { 
      const rates = [1, 1.5, 2]; 
      const next = rates[(rates.indexOf(playbackRate) + 1) % rates.length]; 
      setPlaybackRate(next); 
      if (videoRef.current) videoRef.current.playbackRate = next; 
      if (audioRef.current) audioRef.current.playbackRate = next;
  }; 

  const toggleAspectRatio = () => setAspectRatio(p => p === 'contain' ? 'cover' : 'contain'); 
  const handleFullscreen = () => { if (videoRef.current) videoRef.current.requestFullscreen().catch(console.warn); }; 
  
  const handleVideoEnded = () => { 
      if (resourceGroups?.items && currentEpisode) { 
          const currentIndex = resourceGroups.items.findIndex(res => res.id === currentEpisode.id); 
          if (currentIndex !== -1 && currentIndex < resourceGroups.items.length - 1) { 
              const nextEp = resourceGroups.items[currentIndex + 1]; 
              setCurrentEpisode(nextEp); 
              setIsPlaying(true); 
          } 
      } 
  }; 
  
  const handleVideoError = () => {
      setIsBuffering(false);
      bufferingRef.current = false;
      if (retryCount < 1) {
          console.warn(`Video load failed. Retrying (Attempt ${retryCount + 1}). url: ${videoUrl}`);
          setRetryCount(prev => prev + 1);
          if (videoRef.current) {
              const currentT = seekOnLoad !== null ? seekOnLoad : (videoRef.current.currentTime || currentTime);
              setSeekOnLoad(currentT);
              videoRef.current.load();
              const p = videoRef.current.play();
              if (p) p.catch(console.warn);
          }
      } else {
          console.error(`Video load failed completely after retries. url: ${videoUrl}`);
      }
  };

  const handleLoadedMetadata = () => { 
      if (seekOnLoad !== null && videoRef.current) { 
          videoRef.current.currentTime = seekOnLoad; 
          setSeekOnLoad(null); 
      } 
  }; 
  
  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseFloat(e.target.value);
      setVolume(val);
      if (isAudioTranscodeActive && audioRef.current) {
          audioRef.current.volume = val;
          if (videoRef.current) videoRef.current.volume = 0;
      } else if (videoRef.current) {
          videoRef.current.volume = val;
      }
  };

  useEffect(() => {
      if (videoRef.current) {
         videoRef.current.volume = isAudioTranscodeActive ? 0 : volume;
         videoRef.current.muted = isAudioTranscodeActive ? true : (volume === 0);
      }
      if (audioRef.current) {
         audioRef.current.volume = volume;
      }
  }, [isAudioTranscodeActive, volume]);

  const cancelAudioTranscode = () => {
      if (currentEpisode?.id) {
         const prefix = API_BASE.replace(/\/$/, '');
         fetch(`${prefix}/v1/resources/${currentEpisode.id}/audio-transcode?session_id=${encodeURIComponent(sessionIdRef.current)}`, {
           method: 'DELETE',
           keepalive: true
         }).catch(e => console.warn("Failed to delete audio transcode session", e));
      }

      setPlaybackMode('direct');
      setIsAudioLoading(false);
      
      const shouldPlay = draggedPlayStateRef.current !== null ? draggedPlayStateRef.current : isPlaying;
      if (shouldPlay && videoRef.current) {
           videoRef.current.play().catch(console.warn);
      }
      draggedPlayStateRef.current = null;
  };

  const handlePlaybackModeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
      const mode = e.target.value as any;
      setPlaybackMode(mode);
      if (mode === 'audio_transcode') {
          draggedPlayStateRef.current = isPlaying;
          setIsAudioLoading(true);
          if (videoRef.current) {
              videoRef.current.pause();
          }
          // Preserve isPlaying state
      } else {
          setIsAudioLoading(false);
          // If switching back to direct, and we were playing, play the video
          const shouldPlay = draggedPlayStateRef.current !== null ? draggedPlayStateRef.current : isPlaying;
          if (shouldPlay && videoRef.current) {
               videoRef.current.play().catch(console.warn);
          }
          draggedPlayStateRef.current = null;
      }
  };

  const handleAudioCanPlay = () => {
      if (isAudioLoading) {
          setIsAudioLoading(false);
          if (videoRef.current && audioRef.current) {
              const shouldPlay = draggedPlayStateRef.current !== null ? draggedPlayStateRef.current : isPlaying;
              if (shouldPlay) {
                  videoRef.current.play().catch(console.warn);
                  audioRef.current.play().catch(console.warn);
              }
              if (draggedPlayStateRef.current !== null) {
                  draggedPlayStateRef.current = null;
              }
          }
      }
  };

  return (
  <div className="fixed inset-0 bg-black z-50 flex flex-col"> 
    <div className={`absolute top-0 left-0 w-full p-4 z-20 bg-gradient-to-b from-black/80 to-transparent flex justify-between items-start transition-opacity duration-300 ${isPlaying && !isLocked ? 'opacity-0 hover:opacity-100' : 'opacity-100'} ${isLocked ? 'opacity-0' : ''}`}> 
        <div className="pointer-events-auto"><button onClick={onBack} className="text-white hover:text-primary bg-black/50 px-4 py-2 rounded border border-white/20 flex items-center gap-2"><ChevronLeft size={16} /> 退出播放</button></div> 
        <div className="text-right pointer-events-auto"><h2 className="text-xl font-['Orbitron'] font-bold text-white text-shadow-neon">{movie.title}</h2></div> 
    </div> 
    <div className="flex flex-col lg:flex-row h-full overflow-hidden"> 
        <div className="flex-grow relative bg-black flex items-center justify-center group min-w-0 min-h-0"> 
            {loading ? <div className="text-primary animate-pulse font-['Orbitron']">连接中...</div> : (currentEpisode ? (
            <>
                <video ref={videoRef} src={videoUrl} referrerPolicy="no-referrer" className={`w-full h-full object-${aspectRatio}`} onTimeUpdate={handleTimeUpdate} onPlay={onVideoPlay} onPause={onVideoPause} onWaiting={onVideoWaiting} onPlaying={onVideoPlaying} onEnded={handleVideoEnded} onLoadedMetadata={handleLoadedMetadata} onSeeked={handleSeeked} onClick={!isLocked ? togglePlay : undefined} onError={handleVideoError} autoPlay muted={isAudioTranscodeActive} />
                {isBuffering && isPlaying && !isDraggingSeek && !isAudioLoading && (
                    <div className="absolute inset-0 z-40 bg-black/50 flex flex-col items-center justify-center pointer-events-none">
                        <div className="w-12 h-12 border-4 border-primary/30 border-t-primary rounded-full animate-spin shadow-[0_0_15px_var(--color-primary)]"></div>
                        <div className="mt-4 text-primary font-['Orbitron'] tracking-widest text-sm animate-pulse">BUFFERING...</div>
                    </div>
                )}
                {isAudioTranscodeActive && (
                    <audio ref={audioRef} preload="none" autoPlay={false} onCanPlay={handleAudioCanPlay} />
                )}
                {isAudioLoading && (
                    <EcgLoading text="音频转码同步中..." onCancel={cancelAudioTranscode} />
                )}

                {/* Global Episode Info Tooltip */}
                {hoveredEpInfo && !isLocked && (
                    <div 
                        className="fixed bg-[#121212]/95 backdrop-blur-xl border border-white/10 p-4 rounded-xl shadow-[0_0_40px_rgba(0,0,0,0.9)] pointer-events-none z-50 animate-in fade-in slide-in-from-right-2 max-w-[calc(100vw-64px)] sm:max-w-md md:max-w-xl"
                        style={hoveredEpInfo.rect ? { 
                            top: Math.max(16, Math.min(window.innerHeight - 150, hoveredEpInfo.rect.top)), 
                            left: hoveredEpInfo.rect.left - 16, 
                            transform: 'translateX(-100%)' 
                        } : { bottom: 90, right: 24 }}
                    >
                        <div className="text-[10px] text-primary mb-2 uppercase tracking-widest font-['Orbitron'] font-bold flex items-center gap-1.5 border-b border-white/5 pb-2">
                            <HardDrive size={10} />
                            文件路径详情
                        </div>
                        <div className="flex flex-col gap-2">
                            {hoveredEpInfo.ep !== 'movie' && !hoveredEpInfo.ep.startsWith('MOV_FILE_') && !hoveredEpInfo.ep.startsWith('EXT_') && !hoveredEpInfo.ep.startsWith('SP_') && (
                                <div className="text-white/90 font-bold font-['Orbitron'] text-sm tracking-wide">
                                    <span className="text-primary italic mr-1">EP</span>{hoveredEpInfo.ep}
                                </div>
                            )}
                            <div className="text-xs text-gray-300 break-all leading-relaxed font-mono bg-black/50 p-2 rounded border border-white/5 shadow-inner">
                                {hoveredEpInfo.sources[0].resource_info?.file?.storage_source?.name ? 
                                    `[${hoveredEpInfo.sources[0].resource_info.file.storage_source.name}] /${hoveredEpInfo.sources[0].resource_info.file.relative_path || hoveredEpInfo.sources[0].relative_path || hoveredEpInfo.sources[0].resource_info.file.filename}` 
                                    : hoveredEpInfo.sources[0].source_name ? `[${hoveredEpInfo.sources[0].source_name}] /${hoveredEpInfo.sources[0].relative_path || hoveredEpInfo.sources[0].filename}` 
                                    : (hoveredEpInfo.sources[0].relative_path || hoveredEpInfo.sources[0].filename)}
                            </div>
                            {hoveredEpInfo.sources.length > 1 && (
                                <div className="mt-1 text-[10px] text-gray-500 flex items-center gap-1 bg-white/5 w-fit px-2 py-0.5 rounded-full border border-white/5">
                                    <Server size={10} /> 还有 {hoveredEpInfo.sources.length - 1} 个其他来源可选
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </>
            ) : <div className="text-red-500">资源不可用</div>)} 
            
            {isLocked && <div className="absolute top-4 right-4 text-red-500 flex items-center gap-2 bg-black/50 px-3 py-1 rounded border border-red-500/50 animate-pulse"><Lock size={16} /> 界面已锁定</div>} 
            
            {!isLocked && (<div className={`absolute inset-0 flex flex-col justify-end transition-opacity duration-300 ${isPlaying ? 'opacity-0 group-hover:opacity-100' : 'opacity-100'} bg-gradient-to-t from-black/90 via-transparent to-transparent pointer-events-none`}> 
                <div className="w-full px-8 pb-8 pt-12 pointer-events-auto bg-gradient-to-t from-black via-black/90 to-transparent"> 
                    <div className="backdrop-blur-md bg-black/40 border-t border-white/10 p-4 rounded-t-2xl shadow-[0_-10px_40px_rgba(0,0,0,0.5)] relative overflow-visible"> 
                        <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-primary/50 to-transparent rounded-t-2xl"></div> 
                        <div className="flex items-center gap-4 mb-4 w-full"> 
                            <span className="text-white font-['Rajdhani'] font-bold text-sm min-w-[80px] tracking-widest">{formatDuration(isDraggingSeek ? dragSeekTime : currentTime)} <span className="text-gray-600 mx-1">/</span> {formatDuration(duration)}</span> 
                            <div className="w-full group/progress relative h-6 flex items-center cursor-pointer"> 
                                <div className="absolute inset-0 h-1 bg-white/10 top-1/2 -translate-y-1/2 w-full rounded-full overflow-hidden"> 
                                    <div className="w-full h-full bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0IiBoZWlnaHQ9IjQiPgo8cmVjdCB3aWR0aD0iNCIgaGVpZ2h0PSI0IiBmaWxsPSIjZmZmIiBmaWxsLW9wYWNpdHk9IjAuMDUiLz4KPC9zdmc+')] opacity-50"></div> 
                                </div> 
                                <div className={`absolute h-1 top-1/2 -translate-y-1/2 ${isDraggingSeek ? 'h-2' : 'group-hover/progress:h-2'} rounded-l-full ${!isDraggingSeek ? 'transition-all duration-100 ease-out' : ''}`} style={{ width: `${progress}%`, background: `linear-gradient(90deg, transparent, var(--color-primary))`, boxShadow: `0 0 15px var(--color-primary), 0 0 5px var(--color-primary)`, willChange: 'width' }}> 
                                    <div className={`absolute right-[-8px] top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center transform ${isDraggingSeek ? 'scale-125' : 'scale-0 group-hover/progress:scale-125'} ${!isDraggingSeek ? 'transition-transform duration-200' : ''}`}> 
                                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className={!isDraggingSeek ? "animate-pulse" : ""}> <path d="M12 2L21 7V17L12 22L3 17V7L12 2Z" stroke="var(--color-primary)" strokeWidth="2" fill="black" fillOpacity={isDraggingSeek ? "1" : "0.8"}/> <circle cx="12" cy="12" r="4" fill="var(--color-primary)" className={!isDraggingSeek ? "animate-[ping_2s_ease-in-out_infinite]" : ""} /> </svg> 
                                    </div> 
                                </div> 
                                <input type="range" min="0" max={duration || 100} value={isDraggingSeek ? dragSeekTime : currentTime} onChange={handleSeek} onPointerDown={handleSeekStart} onPointerUp={handleSeekEnd} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-20" /> 
                            </div> 
                            <div className="ml-2"><SciFiProgressRing progress={progress} size={48} isDragging={isDraggingSeek} /></div> 
                        </div> 
                        <div className="flex justify-between items-center border-t border-white/10 pt-4"> 
                            <div className="flex items-center gap-6"> 
                                <button onClick={togglePlay} className="text-white hover:text-primary transition-colors transform hover:scale-110 p-2 border border-white/10 hover:border-primary rounded-sm hover:shadow-[0_0_15px_var(--color-primary)] bg-black/50 backdrop-blur-sm"> {isPlaying ? <Pause size={24} fill="white" /> : <Play size={24} fill="white" />} </button> 
                                <div className="relative flex items-center group/vol"> 
                                    <button className="text-white hover:text-primary transition-colors p-2"> {volume === 0 ? <VolumeX size={24} /> : <Volume2 size={24} />} </button> 
                                    <div className="w-0 overflow-hidden group-hover/vol:w-24 transition-all duration-300 ml-2"> 
                                        <input type="range" min="0" max="1" step="0.1" value={volume} onChange={handleVolumeChange} className="w-20 h-1 bg-gray-600 rounded-lg appearance-none cursor-pointer accent-primary" /> 
                                    </div> 
                                </div> 
                            </div> 
                            <div className="flex items-center gap-4"> 
                                {isAudioTranscodeActive && (
                                    <div className="flex flex-col items-center justify-center opacity-70" title={`Server Audio Transcode Active\nFormat: ${currentEpisode?.playback?.audio?.server_transcode?.mime_type || 'AUDIO'}`}>
                                        <div className="w-2 h-2 rounded-full animate-pulse bg-green-500 shadow-[0_0_8px_var(--color-primary)] cursor-pointer" onClick={handleShowDiagnostics}></div>
                                    </div>
                                )}
                                <select 
                                    value={playbackMode} 
                                    onChange={handlePlaybackModeChange}
                                    className="bg-black/50 text-[10px] font-['Orbitron'] border border-white/20 text-white outline-none focus:border-primary px-2 py-1 rounded"
                                >
                                    <option value="direct">DIRECT</option>
                                    <option value="proxy" disabled>PROXY</option>
                                    <option value="audio_transcode" disabled={!currentEpisode?.playback?.audio?.server_transcode?.available}>
                                        {currentEpisode?.playback?.audio?.server_transcode?.recommended ? 'AUDIO_TRANSCODE (推荐)' : 'AUDIO_TRANSCODE'}
                                    </option>
                                </select>
                                
                                {playingEpisodeSources.length > 1 && (
                                    <div className="relative group/sources" ref={sourceSelectorRef}>
                                        <button 
                                            onClick={() => setShowSourceSelector(!showSourceSelector)}
                                            className={`text-gray-400 hover:text-white hover:scale-110 transition-transform ${showSourceSelector ? 'text-primary' : ''}`}
                                            title="Select Source"
                                        >
                                            <Server size={20} />
                                        </button>
                                        
                                        {showSourceSelector && (
                                            <div 
                                                className="absolute bottom-full right-0 mb-4 bg-[#1f1f23] border border-white/10 rounded-lg shadow-2xl p-2 min-w-[200px] flex flex-col gap-1 z-50 transition-all"
                                                onMouseLeave={() => setHoveredSourcePath(null)}
                                            >
                                                <div className="text-[10px] text-gray-400 font-['Orbitron'] px-2 pb-1 mb-1 border-b border-white/10 flex justify-between">
                                                    <span>SOURCES</span>
                                                    <span className="text-gray-600">{playingEpisodeSources.length} ITEMS</span>
                                                </div>
                                                <div className="max-h-[200px] overflow-y-auto custom-scrollbar flex flex-col pointer-events-auto gap-1">
                                                    {playingEpisodeSources.map((src, i) => {
                                                        const filename = src.resource_info?.file?.filename || src.filename || src.resource_info?.display?.label || src.display_label || src.quality_label || src.resource_info?.technical?.source_label || `Source ${i + 1}`;
                                                        const fullPath = src.resource_info?.file?.relative_path || src.relative_path || filename;
                                                        
                                                        return (
                                                        <button
                                                            key={src.id}
                                                            onClick={() => { handleEpisodeChange(src); setShowSourceSelector(false); }}
                                                            onMouseEnter={() => setHoveredSourcePath(fullPath)}
                                                            className={`px-3 py-2 rounded text-left text-xs transition-colors border max-w-sm w-full ${
                                                                currentEpisode?.id === src.id 
                                                                    ? 'bg-[#00f3ff]/10 border-[#00f3ff]/30 text-[#00f3ff] font-bold shadow-[0_0_8px_rgba(0,243,255,0.3)] drop-shadow-[0_0_2px_rgba(0,243,255,0.5)]' 
                                                                    : 'bg-transparent border-transparent text-gray-400 hover:bg-white/10 hover:text-white'
                                                            }`}
                                                        >
                                                            <span className="block truncate" dir="rtl">
                                                                &lrm;{filename}
                                                            </span>
                                                        </button>
                                                    )})}
                                                </div>
                                                
                                                {hoveredSourcePath && (
                                                    <div className="absolute right-full bottom-0 mr-2 bg-[#121212]/95 border border-white/20 p-3 text-xs text-gray-300 rounded-lg shadow-2xl pointer-events-none max-w-[400px] z-[60] w-[350px] max-h-[300px] overflow-y-auto custom-scrollbar break-all backdrop-blur-md">
                                                        <div className="text-[10px] text-primary mb-1 font-['Orbitron'] flex items-center gap-1">
                                                            <Server size={10} /> FULL PATH
                                                        </div>
                                                        <div className="leading-relaxed opacity-80">
                                                            {hoveredSourcePath}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )}

                                <button onClick={() => setIsLocked(true)} className="text-gray-400 hover:text-white hover:rotate-12 transition-transform" title="Lock Controls"><Lock size={20} /></button> 
                                <button onClick={toggleAspectRatio} className="text-gray-400 hover:text-white hover:scale-110 transition-transform" title="Aspect Ratio">{aspectRatio === 'contain' ? <BoxSelect size={20} /> : <Scan size={20} />}</button> 
                                <button onClick={changePlaybackRate} className="text-xs font-['Orbitron'] font-bold text-white hover:text-primary border border-white/20 px-2 py-1 rounded hover:border-primary transition-all hover:shadow-[0_0_10px_var(--color-primary)]">{playbackRate}x</button> 
                                <Maximize size={24} className="text-white hover:text-primary cursor-pointer hover:scale-110 transition-transform" onClick={handleFullscreen} /> 
                            </div> 
                        </div> 
                    </div> 
                </div> 
            </div>)} 
            
            {isLocked && <button onClick={() => setIsLocked(false)} className="absolute bottom-8 right-8 bg-black/50 p-3 rounded-full border border-red-500 text-red-500 hover:bg-red-500 hover:text-white transition-all z-50 pointer-events-auto"><Lock size={24} /></button>} 
        </div> 
        
        <div className={`shrink-0 w-full lg:w-[350px] lg:min-w-[350px] lg:max-w-[350px] bg-[#121212] border-l border-white/10 flex flex-col z-20 h-full overflow-hidden transition-transform duration-300 ${isLocked ? 'translate-x-full lg:translate-x-full hidden' : 'translate-x-0'}`}> 
            <div className="p-4 border-b border-white/10 shrink-0"> 
                <h3 className="text-sm font-bold text-white mb-3">{movie.title}</h3>
            </div> 
            
            <div className="flex-1 flex flex-col overflow-hidden"> 
                <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4"> 
                    
                    {/* Season Tabs */}
                    {seasonTabs.length > 1 && (
                        <div className="flex border-b border-white/5 pb-2 relative" ref={tabsWrapperRef}>
                            {/* Hidden measurement container */}
                            <div 
                                ref={measureRef} 
                                className="absolute top-0 left-0 flex gap-4 opacity-0 pointer-events-none whitespace-nowrap invisible"
                                aria-hidden="true"
                            >
                                {seasonTabs.map(tab => (
                                    <button
                                        key={`measure-${tab.value}`}
                                        className="py-1 text-xs shrink-0 font-bold px-[2px]"
                                    >
                                        {tab.label}
                                    </button>
                                ))}
                            </div>

                            <div className="flex-1 overflow-hidden">
                                <div className="flex gap-4 pr-1 h-full">
                                    {seasonTabs.slice(0, visibleSeasonCount).map(tab => (
                                        <button
                                            key={tab.value}
                                            onClick={() => setActiveSeason(tab.value)}
                                            className={`py-1 whitespace-nowrap text-xs transition-colors relative shrink-0 flex flex-col items-center ${activeSeason === tab.value ? 'font-bold' : ''} ${tab.isPlaying ? 'text-primary' : activeSeason === tab.value ? 'text-white' : 'text-gray-400 hover:text-white'}`}
                                        >
                                            <span className="flex items-center gap-1">
                                                {tab.label}
                                                {tab.isPlaying && <Activity size={12} className="animate-pulse" />}
                                            </span>
                                            <span className="h-0 overflow-hidden font-bold invisible pointer-events-none flex items-center gap-1" aria-hidden="true">
                                                {tab.label}
                                                {tab.isPlaying && <Activity size={12} />}
                                            </span>
                                            {activeSeason === tab.value && (
                                                <div className={`absolute bottom-[-10px] left-0 w-full h-[2px] rounded-t-full ${tab.isPlaying ? 'bg-primary shadow-[0_0_8px_var(--color-primary)]' : 'bg-white shadow-[0_0_8px_rgba(255,255,255,0.5)]'}`}></div>
                                            )}
                                        </button>
                                    ))}
                                </div>
                            </div>
                            
                            {seasonTabs.length > visibleSeasonCount && (
                                <div className="relative group/dropdown shrink-0 z-20 pl-2 flex items-center justify-center">
                                    <button className="flex items-center justify-center text-gray-400 hover:text-white cursor-pointer h-full transition-colors w-[24px]">
                                        <LayoutGrid size={14} className="group-hover/dropdown:text-primary transition-colors" />
                                    </button>
                                    <div className="absolute top-full right-0 pt-3 w-48 opacity-0 invisible group-hover/dropdown:opacity-100 group-hover/dropdown:visible transition-all">
                                        <div className="bg-[#1f1f23] border border-white/10 rounded-lg shadow-2xl flex flex-col py-1 max-h-[300px] overflow-y-auto custom-scrollbar">
                                            {seasonTabs.slice(visibleSeasonCount).map(tab => (
                                                <button
                                                    key={`drop-${tab.value}`}
                                                    onClick={() => setActiveSeason(tab.value)}
                                                    className={`px-4 py-2 text-left text-xs transition-colors flex items-center justify-between ${activeSeason === tab.value ? 'bg-white/5 font-bold' : 'hover:bg-white/10 hover:text-white'} ${tab.isPlaying ? 'text-primary' : activeSeason === tab.value ? 'text-white' : 'text-gray-400'}`}
                                                >
                                                    <span>{tab.label}</span>
                                                    {tab.isPlaying && <Activity size={12} className="animate-pulse opacity-70" />}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="flex justify-between items-center text-xs text-gray-400 font-['Orbitron']">
                        <span>{activeSeason === 'standalone' ? '正片' : 'Episodes'}</span>
                        <span>{totalEps} ITEMS</span>
                    </div>

                    {/* Pagination Tabs */}
                    {totalPages > 1 && (
                        <div className="flex gap-2 overflow-x-auto no-scrollbar border-b border-white/5 pb-2">
                            {Array.from({ length: totalPages }).map((_, i) => {
                                const start = i * EPISODES_PER_PAGE + 1;
                                const end = Math.min((i + 1) * EPISODES_PER_PAGE, totalEps);
                                const label = `${start}-${end}`;
                                return (
                                    <button
                                        key={i}
                                        onClick={() => setEpisodePage(i)}
                                        className={`px-3 py-1 text-xs rounded transition-colors whitespace-nowrap border ${
                                            episodePage === i 
                                                ? 'bg-primary/10 border-primary text-primary' 
                                                : 'bg-white/5 border-transparent text-gray-400 hover:text-white hover:bg-white/10'
                                        }`}
                                    >
                                        {label}
                                    </button>
                                );
                            })}
                        </div>
                    )}

                    <motion.div 
                        key={`${activeSeason}-${episodePage}`}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.2 }}
                        className="grid gap-1.5 grid-cols-5 sm:grid-cols-6 lg:grid-cols-5"
                    >
                        {currentEpEntries.map(([ep, sources]) => {
                            const isPlaying = sources.some(s => s.id === currentEpisode?.id);
                            const isWide = ep === 'movie' || ep.length > 4 || isNaN(Number(ep));
                            
                            return (
                                <div key={ep} className={`relative group/epbtn ${isWide ? 'col-span-full' : ''}`}>
                                    <button
                                        onMouseEnter={(e) => {
                                            const rect = e.currentTarget.getBoundingClientRect();
                                            setHoveredEpInfo({ ep, sources, rect });
                                        }}
                                        onMouseLeave={() => setHoveredEpInfo(null)}
                                        onClick={() => {
                                            if (!isPlaying) handleEpisodeChange(sources[0]);
                                        }}
                                        className={`
                                            relative flex flex-col items-center justify-center rounded-lg border transition-all duration-300 w-full h-full group
                                            ${isWide ? 'px-3 py-2.5 text-left items-start justify-start' : 'aspect-square backdrop-blur-sm overflow-hidden'}
                                            ${isPlaying 
                                                ? 'bg-gradient-to-br from-primary/20 to-primary/5 border-primary/70 text-primary shadow-[0_0_15px_rgba(var(--color-primary-rgb),0.3),inset_1px_1px_3px_rgba(255,255,255,0.3)] scale-[1.02]' 
                                                : 'bg-gradient-to-br from-white/5 to-transparent border-white/10 text-gray-300 shadow-[4px_4px_10px_rgba(0,0,0,0.5),inset_1px_1px_1px_rgba(255,255,255,0.05)] hover:from-white/10 hover:to-white/5 hover:border-white/30 hover:text-white hover:-translate-y-0.5 hover:shadow-[6px_6px_15px_rgba(0,0,0,0.6),inset_1px_1px_2px_rgba(255,255,255,0.1)]'
                                            }
                                        `}
                                    >
                                        {isPlaying && !isWide && (
                                            <Activity size={12} className="absolute top-1 right-1 animate-pulse opacity-70" />
                                        )}
                                        
                                        {isWide ? (() => {
                                            const src = sources[0];
                                            const techInfo = src.resource_info?.technical;
                                            
                                            // Badges extraction
                                            const resBadge = techInfo?.video_resolution_badge_label || src.media_info?.resolution;
                                            const sourceBadge = techInfo?.source_label;
                                            const isHdr = techInfo?.video_dynamic_range_is_hdr;
                                            const dynamicRange = techInfo?.video_dynamic_range_label;
                                            const videoCodec = techInfo?.video_codec_label || src.media_info?.video_codec;
                                            const audioSummary = techInfo?.audio_summary_label || techInfo?.audio_codec_label || src.media_info?.audio_codec;
                                            const isAtmos = techInfo?.audio_is_atmos;
                                            const rawSize = src.size_bytes || src.resource_info?.file?.size_bytes;
                                            const fileSize = rawSize ? (rawSize / 1024 / 1024 / 1024).toFixed(2) + ' GB' : null;
                                            
                                            return (
                                            <div className="flex flex-col w-full px-1">
                                                <div className="flex items-start gap-3 w-full mb-2">
                                                    <div className={`mt-0.5 p-1.5 rounded-md ${isPlaying ? 'bg-primary/20 text-primary shadow-[0_0_10px_rgba(var(--color-primary-rgb),0.4)]' : 'bg-white/5 text-gray-400 group-hover:text-white'}`}>
                                                        {isPlaying ? <Activity size={14} className="animate-pulse" /> : <Play size={14} />}
                                                    </div>
                                                    <div className="flex flex-col flex-1 min-w-0">
                                                        <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                                                            {src.resource_info?.file?.storage_source?.name && (
                                                                <span className="px-1.5 py-0.5 text-[9px] font-bold tracking-wider text-black bg-primary/90 rounded-sm uppercase inline-block whitespace-nowrap shadow-[0_0_8px_rgba(var(--color-primary-rgb),0.3)]">
                                                                    {src.resource_info.file.storage_source.name}
                                                                </span>
                                                            )}
                                                            <span className={`font-semibold text-xs leading-snug tracking-wide line-clamp-2 ${isPlaying ? 'text-[#00f3ff] drop-shadow-[0_0_8px_rgba(0,243,255,0.8)]' : 'text-gray-200 group-hover:text-white'}`}>
                                                                {src.resource_info?.display?.title || src.resource_info?.file?.filename || src.filename}
                                                            </span>
                                                        </div>
                                                    </div>
                                                </div>
                                                
                                                <div className="flex flex-wrap gap-1.5 mt-1 ml-9">
                                                    {resBadge && (
                                                        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold font-['Orbitron'] tracking-wider ${isPlaying ? 'bg-primary/20 text-primary border-primary/40 shadow-[0_0_8px_rgba(var(--color-primary-rgb),0.3)]' : 'bg-[#00f3ff]/10 text-[#00f3ff] border-[#00f3ff]/30 shadow-[0_0_8px_rgba(0,243,255,0.2)] group-hover:bg-[#00f3ff]/20'}`}>
                                                            {resBadge}
                                                        </span>
                                                    )}
                                                    {sourceBadge && (
                                                        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-semibold tracking-wide ${isPlaying ? 'bg-primary/10 text-primary/90 border-primary/30' : 'bg-[#00f3ff]/10 text-[#00f3ff] border-[#00f3ff]/30 shadow-[0_0_8px_rgba(0,243,255,0.2)] group-hover:bg-[#00f3ff]/20'}`}>
                                                            {sourceBadge.replace('Blu-ray', 'Bluray')}
                                                        </span>
                                                    )}
                                                    {dynamicRange && (
                                                        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${isHdr || dynamicRange.toUpperCase().includes('HDR') || dynamicRange.toUpperCase().includes('VISION') ? 'bg-[rgba(245,240,11,0.08)] text-[rgb(245,240,11)] border-[rgba(245,240,11,0.5)] shadow-[0_0_8px_rgba(245,240,11,0.25)]' : 'bg-gray-500/10 text-gray-400 border-gray-500/20'} `}>
                                                            {dynamicRange}
                                                        </span>
                                                    )}
                                                    {videoCodec && !videoCodec.toUpperCase().includes('HEVC') && (
                                                        <span className="px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-gray-400 text-[9px] font-mono group-hover:bg-white/10 group-hover:text-gray-300">
                                                            {videoCodec}
                                                        </span>
                                                    )}
                                                    {audioSummary && (
                                                        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${isAtmos || audioSummary.toUpperCase().includes('DOLBY') || audioSummary.toUpperCase().includes('ATMOS') ? 'bg-[rgba(199,34,238,0.08)] text-[rgb(199,34,238)] border-[rgba(199,34,238,0.5)] shadow-[0_0_8px_rgba(199,34,238,0.25)]' : 'bg-white/5 text-gray-400 border-white/10'}`}>
                                                            {audioSummary.toUpperCase().includes('ATMOS') && !audioSummary.toUpperCase().includes('DOLBY') ? 'Dolby Atmos' : audioSummary}
                                                        </span>
                                                    )}
                                                    {fileSize && (
                                                        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-mono whitespace-nowrap ml-auto ${isPlaying ? 'bg-primary/10 text-primary/80 border-primary/20' : 'bg-transparent text-gray-500 border-transparent'}`}>
                                                            {fileSize}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                            );
                                        })() : (
                                            <span className="font-['Orbitron'] font-semibold z-10 flex items-center gap-2 text-xs">
                                                {ep}
                                            </span>
                                        )}
                                    </button>
                                </div>
                            );
                        })}

                        {Object.keys(episodeGroups).length === 0 && (
                            <div className="p-4 text-center text-gray-500 text-xs col-span-full border border-dashed border-white/10 rounded-lg">
                                NO MEDIA FOUND
                            </div>
                        )}
                    </motion.div>
                </div> 
            </div> 
        </div> 
    </div> 
  </div>
  ); 
}