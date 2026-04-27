import React, { useState, useEffect, useMemo, useRef } from 'react';
import { ChevronLeft, PlayCircle, Plus, Download, Share2, Star, User, RotateCcw, FileVideo, Play, Cpu, HardDrive, Music, Box, Monitor, Activity, Database, Sparkles, ArrowRight, Terminal, Zap, RefreshCw } from 'lucide-react';
import { Movie, PlayOptions, HistoryItem } from '../types';
import { movieService } from '../api';
import { formatBytes, formatDuration } from '../utils';
import { MovieCard } from '../components/movies/Cards';
import { TechBadge } from '../components/ui/CyberComponents';

interface MovieDetailProps {
  movie: Movie;
  history: HistoryItem[];
  onBack: () => void;
  onPlay: (options: PlayOptions) => void;
  onMovieSelect: (m: Movie) => void;
  isFavorite: boolean;
  onToggleFavorite: (m: Movie) => void;
  onUpdateMovie?: (m: Movie) => void;
}

export const MovieDetail: React.FC<MovieDetailProps> = ({ movie, history, onBack, onPlay, onMovieSelect, isFavorite, onToggleFavorite, onUpdateMovie }) => { 
  const [fullMovieData, setFullMovieData] = useState<Movie>(movie);
  const [resourceGroups, setResourceGroups] = useState<import('../types').MovieResourceGroups | null>(null);
  const [loading, setLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [recommendations, setRecommendations] = useState<Movie[]>([]);
  const [activeSeason, setActiveSeason] = useState<number | null>(null);

  const handleRefreshMovie = async () => {
    setIsRefreshing(true);
    try {
      const updatedMovie = await movieService.refreshMetadata(String(movie.id), { media_type_hint: movie.type as any });
      if (updatedMovie) {
        setFullMovieData({
          ...updatedMovie,
          target_season: movie.target_season
        });
        if (onUpdateMovie) onUpdateMovie(updatedMovie);
      }
    } catch(e) {
      console.warn("Refresh failed", e);
    } finally {
      setIsRefreshing(false);
    }
  };
  
  // Ref for horizontal scrolling of recommendations
  const scrollRef = useRef<HTMLDivElement>(null); 
  const scroll = (direction: 'left' | 'right') => { 
    if (scrollRef.current) { 
      const { current } = scrollRef; 
      const scrollAmount = direction === 'left' ? -300 : 300; 
      current.scrollBy({ left: scrollAmount, behavior: 'smooth' }); 
    } 
  };

  // Fetch detailed info (resources) & Recommendations when movie changes
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      
      // Parallel fetch for speed
      const [detail, resData, recs] = await Promise.all([
        movieService.getDetail(movie.id),
        movieService.getResources(movie.id),
        movieService.getContextRecommendations(String(movie.id), 8, movie.type === 'tv' || movie.type === 'series' || !!movie.season ? 'tv' : 'movie')
      ]);

      if (detail) {
        // preserve season-level overrides from the pseudo-movie
        setFullMovieData({
          ...detail,
          title: movie.title || detail.title,
          cover_url: movie.cover_url || detail.cover_url,
          poster_url: movie.poster_url || detail.poster_url,
          desc: detail.desc || movie.desc,
          overview: detail.overview || movie.overview,
          target_season: movie.target_season
        });
      }
      if (resData) {
        setResourceGroups(resData);
        if (movie.target_season !== undefined) {
            setActiveSeason(movie.target_season);
        } else if (resData.groups?.seasons && resData.groups.seasons.length > 0) {
            setActiveSeason(resData.groups.seasons[0].season);
        }
      }
      if (recs) {
        setRecommendations(recs);
      }

      setLoading(false);
    };

    loadData();
    window.scrollTo(0, 0);
  }, [movie.id]);

  const safeId = String(fullMovieData.id || 'def');
  const hue = parseInt(safeId.split('-').pop() || '0') * 40; 
  
  // Resources check - prefer resourceGroups for structured display
  const hasResources = (resourceGroups?.items?.length || 0) > 0;
  const primaryResource = resourceGroups?.items?.[0] || null;
  const isSeries = (resourceGroups?.summary?.season_count || 0) > 0;
  const currentSeasonGroup = resourceGroups?.groups?.seasons?.find(g => g.season === activeSeason);

  // Dynamically compute display data based on active season
  const displayData = useMemo(() => {
     let poster = fullMovieData.cover_url || fullMovieData.poster_url;
     console.log("MovieDetail displayData poster:", poster, "fullMovieData:", fullMovieData);
     let overview = fullMovieData.overview || fullMovieData.desc;
     
     if (activeSeason !== null && fullMovieData.season_cards) {
         const sc = fullMovieData.season_cards.find(c => c.season === activeSeason);
         if (sc) {
             if (sc.poster_url && sc.has_distinct_poster) {
                 poster = sc.poster_url;
             }
             if (sc.overview) {
                 overview = sc.overview;
             }
         }
     }
     
     return {
         poster_url: poster,
         overview: overview
     };
  }, [fullMovieData, activeSeason]);

  const currentSeasonGroupItems = useMemo(() => {
    if (!currentSeasonGroup || !resourceGroups?.items) return [];
    return currentSeasonGroup.resource_ids.map(id => resourceGroups.items.find(r => r.id === id)).filter(Boolean) as import('../types').Resource[];
  }, [currentSeasonGroup, resourceGroups?.items]);

  // Calculate Resume Record
  const resumeRecord = useMemo(() => {
    if (!resourceGroups?.items) return null;

    // First check user_data from the current active season
    let targetUserData = currentSeasonGroup?.user_data;

    // If no season user_data or it has no progress, fall back to movie-level user_data ONLY IF it's not a series
    // If it's a series, we don't want to use movie-level user_data because it might belong to another season.
    if (!targetUserData || typeof targetUserData.progress !== 'number') {
      if (!isSeries && fullMovieData.user_data) {
          targetUserData = fullMovieData.user_data;
      }
    }

    // Validate that targetUserData belongs to the current active season if it's a series
    let validResource = null;
    if (targetUserData && targetUserData.resource_id) {
        validResource = resourceGroups.items.find(r => r.id === targetUserData!.resource_id);
        if (validResource && isSeries && currentSeasonGroup) {
            // If we are looking at a specific season, ensure the resource belongs to it
            // By checking if the ID exists in current season resources
            if (!currentSeasonGroup.resource_ids.includes(validResource.id)) {
                validResource = null;
                targetUserData = undefined;
            }
        }
    }

    // Attempt to construct resume record from user_data
    if (validResource && targetUserData && targetUserData.progress > 5 && targetUserData.duration > 0 && (targetUserData.progress / targetUserData.duration) < 0.95) {
      return {
          resourceId: targetUserData.resource_id,
          progress: targetUserData.progress,
          duration: targetUserData.duration,
          filename: targetUserData.filename || validResource.resource_info?.file?.filename || validResource.filename || 'Unknown File',
          season: targetUserData.season || validResource.resource_info?.display?.season || validResource.season,
          episode: targetUserData.episode || validResource.resource_info?.display?.episode || validResource.episode
      };
    }

    // Fallback to legacy history array check
    if (history) {
      // Create a set of resource IDs belonging to this movie/season
      let resourceIdsToMatch: string[] = [];
      if (isSeries) {
          if (currentSeasonGroup) {
              resourceIdsToMatch = currentSeasonGroup.resource_ids;
          }
      } else {
          resourceIdsToMatch = resourceGroups.items.map(r => r.id);
      }
      const movieResourceIds = new Set(resourceIdsToMatch);
      
      if (movieResourceIds.size > 0) {
          // Find the first history item that exists in this season's resources
          const match = history.find(h => movieResourceIds.has(h.resourceId));
          
          if (match && match.progress > 5 && match.duration > 0 && (match.progress / match.duration) < 0.95) {
              const resourceDetail = resourceGroups.items.find(r => r.id === match.resourceId);
              return {
                  resourceId: match.resourceId,
                  progress: match.progress,
                  duration: match.duration,
                  filename: resourceDetail?.resource_info?.file?.filename || resourceDetail?.filename || 'Unknown File',
                  season: resourceDetail?.resource_info?.display?.season || resourceDetail?.season,
                  episode: resourceDetail?.resource_info?.display?.episode || resourceDetail?.episode
              };
          }
      }
    }

    return null;
  }, [history, resourceGroups, currentSeasonGroup, isSeries, fullMovieData.user_data]);

  const handlePlay = () => {
    if (resumeRecord) {
        onPlay({ resourceId: resumeRecord.resourceId });
        return;
    }

    let playResource = primaryResource;
    if (isSeries && currentSeasonGroupItems.length > 0) {
        playResource = currentSeasonGroupItems[0];
    }
    if (playResource) {
      onPlay({ resourceId: playResource.id });
    }
  };

  const handleResume = () => {
    if (resumeRecord) {
        onPlay({ 
            resourceId: resumeRecord.resourceId, 
            startTime: resumeRecord.progress 
        });
    }
  };

  const derivedTechSpecs = useMemo(() => {
    // Start with the basic specs from fullMovieData
    let specs: import('../types').TechSpecs = { ...(fullMovieData.tech_specs || {}) };
    
    // If we have resources, enrich or override with the most detailed info
    if (resourceGroups?.items && resourceGroups.items.length > 0) {
      // Find the "primary" resource for display
      let primaryRes = null;
      if (isSeries && activeSeason !== null && currentSeasonGroupItems.length > 0) {
        primaryRes = currentSeasonGroupItems[0];
      } else {
        primaryRes = resourceGroups.items[0];
      }

      if (primaryRes) {
        const res = primaryRes as any;
        const tech = res.resource_info?.technical;
        const file = res.resource_info?.file;

        if (tech) {
          let resolution = tech.video_resolution_label;
          if (resolution && (resolution.toUpperCase().includes('2160') || resolution.toUpperCase().includes('3840') || tech.flag_is_4k)) {
            resolution = '4K';
          }
          if (resolution && resolution.toUpperCase() === 'UNKNOWN') {
            resolution = '';
          }

          specs = {
            ...specs,
            resolution: resolution || specs.resolution,
            codec: (tech.video_codec_code && tech.video_codec_code.toUpperCase() !== 'UNKNOWN') ? tech.video_codec_code.toUpperCase() : specs.codec,
            codec_label: (tech.video_codec_label && tech.video_codec_label.toUpperCase() !== 'UNKNOWN') ? tech.video_codec_label : specs.codec_label,
            audio: (tech.audio_codec_code && tech.audio_codec_code.toUpperCase() !== 'UNKNOWN') ? tech.audio_codec_code.toUpperCase() : specs.audio,
            audio_summary: (tech.audio_summary_label && tech.audio_summary_label.toUpperCase() !== 'UNKNOWN') ? tech.audio_summary_label : specs.audio_summary,
            hdr: (tech.video_dynamic_range_label && tech.video_dynamic_range_label.toUpperCase() !== 'UNKNOWN') ? tech.video_dynamic_range_label : specs.hdr,
            source_label: (tech.source_label && tech.source_label.toUpperCase() !== 'UNKNOWN') ? tech.source_label : specs.source_label,
            bit_depth: (tech.video_bit_depth_label && tech.video_bit_depth_label.toUpperCase() !== 'UNKNOWN') ? tech.video_bit_depth_label : specs.bit_depth,
            flag_is_4k: tech.flag_is_4k ?? specs.flag_is_4k,
            flag_is_remux: tech.flag_is_remux ?? specs.flag_is_remux,
            flag_is_hdr: tech.flag_is_hdr ?? specs.flag_is_hdr,
            flag_is_dolby_vision: tech.flag_is_dolby_vision ?? specs.flag_is_dolby_vision,
            audio_is_atmos: tech.audio_is_atmos ?? specs.audio_is_atmos,
            extra_tags: (tech.extra_tags || specs.extra_tags)?.filter((tag: string) => 
              tag && tag.toUpperCase() !== 'UNKNOWN' && tag.toUpperCase() !== 'REMUX'
            ),
            size: res.size_bytes ? formatBytes(res.size_bytes) : (file?.size_bytes ? formatBytes(file.size_bytes) : specs.size),
            storage_name: file?.storage_source?.name || res.source_name,
            bitrate: tech.video_bitrate_label || specs.bitrate,
          };
        } else if (res.media_info) {
          let resolution = res.media_info.resolution;
          if (resolution && (resolution.toUpperCase().includes('2160') || resolution.toUpperCase() === '4K' || resolution.toUpperCase().includes('3840'))) {
            resolution = '4K';
          }
          if (resolution && resolution.toUpperCase() === 'UNKNOWN') {
            resolution = '';
          }

          specs = {
            ...specs,
            resolution: resolution || specs.resolution,
            codec: (res.media_info.video_codec && res.media_info.video_codec.toUpperCase() !== 'UNKNOWN') ? res.media_info.video_codec.toUpperCase() : specs.codec,
            audio: (res.media_info.audio_codec && res.media_info.audio_codec.toUpperCase() !== 'UNKNOWN') ? res.media_info.audio_codec.toUpperCase() : specs.audio,
            bitrate: res.media_info.bitrate ? `${(res.media_info.bitrate / 1000).toFixed(1)} Mbps` : specs.bitrate,
            hdr: (res.media_info.hdr && res.media_info.hdr.toUpperCase() !== 'UNKNOWN') ? res.media_info.hdr : specs.hdr,
            size: res.size_bytes ? formatBytes(res.size_bytes) : specs.size,
            extra_tags: specs.extra_tags?.filter((tag: string) => 
              tag && tag.toUpperCase() !== 'UNKNOWN' && tag.toUpperCase() !== 'REMUX'
            ),
          };
        }
      }
    }
    
    return specs;
  }, [fullMovieData.tech_specs, resourceGroups, isSeries, activeSeason, currentSeasonGroupItems]);

  const shouldShowQualityBadge = useMemo(() => {
    if (!fullMovieData.quality_badge) return false;
    const badge = fullMovieData.quality_badge.toUpperCase();
    
    // If it's a REMUX, we want to show the REMUX badge specifically, 
    // but we'll handle the redundancy here. 
    // If flag_is_remux is true, the dedicated REMUX badge will show up below.
    if (badge === 'REMUX' && derivedTechSpecs.flag_is_remux) return false;
    
    // If the resolution says 4K, we don't need a redundant 4K quality badge
    if ((badge === '4K' || badge === '4K UHD') && 
        (derivedTechSpecs.flag_is_4k || derivedTechSpecs.resolution?.toUpperCase().includes('4K'))) {
      return false;
    }
    
    return true;
  }, [fullMovieData.quality_badge, derivedTechSpecs]);

  return (
    <div className="relative min-h-screen w-full text-white pt-20 pb-12 overflow-hidden" onClick={onBack}> 
      {/* Immersive Backdrop Background */}
      <div className="absolute inset-0 z-0 pointer-events-none"> 
          {/* Background Color Base */}
          <div className="absolute inset-0 bg-[#050505]"></div>

          {fullMovieData.backdrop_url ? (
            <>
                {/* High Res Backdrop Image */}
                <img 
                    src={fullMovieData.backdrop_url}
                    alt="Backdrop"
                    referrerPolicy="no-referrer"
                    className="absolute inset-0 w-full h-full object-cover object-top transition-opacity duration-1000" 
                    style={{ opacity: 0.85 }}
                />
                
                {/* Gradient Overlay - Bottom Fade (Seamless blend to footer/content) */}
                <div className="absolute inset-0 bg-gradient-to-t from-[#050505] via-[#050505]/60 to-transparent via-40%"></div>
                
                {/* Gradient Overlay - Left Fade (Make text readable) */}
                <div className="absolute inset-0 bg-gradient-to-r from-[#050505] via-[#050505]/60 to-transparent via-40%"></div>

                {/* Gradient Overlay - Top Fade (Navbar visibility) */}
                <div className="absolute top-0 left-0 right-0 h-32 bg-gradient-to-b from-[#050505]/60 to-transparent"></div>
            </>
          ) : (
            /* Fallback Abstract Gradient if no backdrop */
            <>
                <div className="absolute inset-0 opacity-20" style={{ backgroundImage: `radial-gradient(circle at 70% 20%, hsla(${hue}, 70%, 50%, 0.3), transparent 60%)`, }}></div>
                <div className="absolute inset-0 bg-gradient-to-t from-[#050505] via-[#050505]/80 to-transparent"></div>
            </>
          )}
      </div> 
    
      <div className="w-full max-w-[2500px] mx-auto px-4 md:px-8 lg:px-12 relative z-10 pt-4" onClick={(e) => e.stopPropagation()}> 
        <button onClick={onBack} className="group flex items-center gap-2 text-gray-400 hover:text-primary mb-8 transition-colors"> <ChevronLeft className="group-hover:-translate-x-1 transition-transform" /> <span className="font-['Rajdhani'] font-bold tracking-wider">返回</span> </button> 
        
        <div className="flex flex-col lg:flex-row gap-8 lg:gap-12 mb-20"> 
            <div className="w-full sm:w-[300px] lg:w-[380px] xl:w-[480px] flex-shrink-0 flex flex-col gap-6"> 
                <div className="aspect-[2/3] w-full bg-[#0a0a12] border border-white/10 relative overflow-hidden group shadow-2xl rounded-sm"> 
                    {fullMovieData.cover_url ? (
                        <img 
                            src={fullMovieData.cover_url} 
                            alt={fullMovieData.title} 
                            referrerPolicy="no-referrer"
                            className="absolute inset-0 w-full h-full object-cover" 
                        />
                    ) : (
                        <div className="absolute inset-0 flex flex-col items-center justify-center p-8 text-center border-4 border-double border-white/5 m-2"> 
                            <div className="text-6xl mb-4 opacity-20"> {fullMovieData.title.charAt(0)} </div> 
                            <h2 className="text-3xl font-bold text-white/80" data-text={fullMovieData.title}> {fullMovieData.title} </h2> 
                        </div>
                    )} 
                </div> 
            </div> 
            
            <div className="flex-1 mt-0 lg:mt-6"> 
                <div className="flex items-start justify-between gap-4">
                    <h1 className="text-4xl md:text-5xl font-black text-white mb-4 tracking-tight leading-tight drop-shadow-lg"> {fullMovieData.title} </h1> 
                </div>
                {fullMovieData.original_title && <h2 className="text-xl text-gray-400 font-['Noto_Sans_SC'] mb-6 drop-shadow-md">{fullMovieData.original_title}</h2>}
                <div className="flex flex-wrap items-center gap-4 text-gray-300 font-['Rajdhani'] text-lg mb-8 drop-shadow-md font-medium"> 
                    <div className="flex items-center gap-1 text-secondary">
                        <Star size={18} fill="currentColor" />
                        <span className="font-bold text-white ml-1">{fullMovieData.rating}</span>
                    </div>
                    <span className="w-1 h-1 bg-gray-500 rounded-full mx-1"></span>
                    <span className="text-white">{fullMovieData.year}</span> 
                    {(() => {
                        const durationStr = fullMovieData.duration ? formatDuration(fullMovieData.duration) : '00:00';
                        const isSeries = fullMovieData.type === 'series' || fullMovieData.type === 'tv' || !!fullMovieData.season;
                        if (durationStr !== '00:00' && !isSeries) {
                            return (
                                <>
                                    <span className="w-1 h-1 bg-gray-500 rounded-full mx-1"></span>
                                    <span className="text-white">{durationStr}</span>
                                </>
                            );
                        }
                        return null;
                    })()}
                    {(() => {
                        const filteredTags = fullMovieData.tags?.filter(tag => tag && tag !== '花絮' && !tag.includes('花絮')) || [];
                        if (filteredTags.length > 0) {
                            return (
                                <>
                                    <span className="w-1 h-1 bg-gray-500 rounded-full mx-1"></span>
                                    <div className="flex flex-wrap gap-2">
                                    {filteredTags.slice(0, 4).map((tag, idx) => (
                                        <React.Fragment key={tag}>
                                            <span className="text-white/90 hover:text-white transition-colors cursor-default">{tag}</span>
                                            {idx !== Math.min(filteredTags.length, 4) - 1 && <span className="text-white/40">/</span>}
                                        </React.Fragment>
                                    ))}
                                    </div>
                                </>
                            );
                        }
                        return null;
                    })()}
                    
                    {fullMovieData.isUnscraped && (
                        <>
                            <span className="w-1 h-1 bg-gray-500 rounded-full mx-1"></span>
                            <div className="flex items-center gap-2 bg-red-900/40 border border-red-500/50 rounded-sm px-2 py-0.5 text-red-400 ml-2">
                                <span className="font-bold tracking-wider text-[10px]">UNSCRAPED RAW</span>
                            </div>
                        </>
                    )}
                </div> 

                {/* Tech Specs Elite - The Hardcore Section */}
                <div className="flex flex-wrap gap-3 mb-8">
                    {/* 1. Remux (Elite First) - Blue Style */}
                    {derivedTechSpecs.flag_is_remux && (
                        <TechBadge className="bg-primary/20 text-primary border-primary/50 font-black shadow-[0_0_15px_rgba(var(--color-primary-rgb),0.3)] px-3 py-1.5 flex items-center gap-2">
                             <Zap size={14} className="fill-current" />
                             <span className="text-sm tracking-widest uppercase">REMUX</span>
                        </TechBadge>
                    )}

                    {/* 2. Quality Badge (Primary) - Only if not redundant */}
                    {shouldShowQualityBadge && (
                        <TechBadge className="bg-primary/10 text-primary border-primary/30 font-bold px-3 py-1.5 flex items-center gap-2">
                            <span className="text-sm tracking-widest">{fullMovieData.quality_badge?.toUpperCase()}</span>
                        </TechBadge>
                    )}

                    {/* 3. Resolution (e.g. 4K, 1080P) */}
                    {((derivedTechSpecs.resolution && derivedTechSpecs.resolution.toUpperCase() !== 'UNKNOWN') || derivedTechSpecs.flag_is_4k) && (
                        <TechBadge className="bg-black/60 border-primary/40 text-primary px-3 py-1.5 flex items-center gap-2">
                            <Monitor size={14} />
                            <span className="text-sm font-bold tracking-wider">{derivedTechSpecs.resolution && derivedTechSpecs.resolution.toUpperCase() !== 'UNKNOWN' ? derivedTechSpecs.resolution : (derivedTechSpecs.flag_is_4k ? '4K' : '')}</span>
                        </TechBadge>
                    )}

                    {/* 4. Video HDR Logic - Bright Yellow Style */}
                    {(derivedTechSpecs.flag_is_dolby_vision || derivedTechSpecs.flag_is_hdr || (derivedTechSpecs.hdr && derivedTechSpecs.hdr.toUpperCase() !== 'UNKNOWN')) && (
                        <TechBadge 
                            className="bg-[rgba(245,240,11,0.05)] border-[rgba(245,240,11,0.5)] text-[rgb(245,240,11)] px-3 py-1.5 font-black uppercase text-sm tracking-tight shadow-[0_0_10px_rgba(245,240,11,0.2)]"
                        >
                            {derivedTechSpecs.flag_is_dolby_vision ? 'Dolby Vision' : (derivedTechSpecs.flag_is_hdr ? 'HDR10' : derivedTechSpecs.hdr)}
                        </TechBadge>
                    )}

                    {/* 5. Audio Elite (Atmos, DTS:X etc) - Vivid Purple Style */}
                    {(derivedTechSpecs.audio_is_atmos || (derivedTechSpecs.audio && derivedTechSpecs.audio.toUpperCase() !== 'UNKNOWN')) && (
                        <TechBadge 
                            className="bg-[rgba(199,34,238,0.05)] border-[rgba(199,34,238,0.5)] text-[rgb(199,34,238)] px-3 py-1.5 flex items-center gap-2 shadow-[0_0_10px_rgba(199,34,238,0.2)]"
                        >
                            <Music size={14} />
                            <span className="text-sm font-bold tracking-wider uppercase">{derivedTechSpecs.audio_is_atmos ? 'Dolby Atmos' : derivedTechSpecs.audio}</span>
                        </TechBadge>
                    )}

                    {/* 6. Size (Modified from Codec as requested) */}
                    {derivedTechSpecs.size && (
                        <TechBadge className="bg-black/40 border-[rgb(13,143,207)] text-[rgb(13,143,207)] px-3 py-1.5 text-xs font-['Orbitron']">
                            {derivedTechSpecs.size}
                        </TechBadge>
                    )}

                    {/* 7. Extra Tags */}
                    {derivedTechSpecs.extra_tags?.filter(tag => tag && tag.toUpperCase() !== 'UNKNOWN' && tag.toUpperCase() !== 'REMUX' && tag !== '花絮' && !tag.includes('花絮')).map(tag => (
                        <TechBadge key={tag} className="bg-black/40 border-purple-500/40 text-purple-400 px-3 py-1.5 text-xs font-['Orbitron'] uppercase tracking-widest">
                            {tag}
                        </TechBadge>
                    ))}
                </div>
                
                <div className="flex flex-wrap gap-4 mb-10 items-stretch">
                    {/* Resume Button */}
                    {resumeRecord && (
                        <button onClick={handleResume} style={{ backgroundColor: 'var(--color-primary)' }} className="relative group h-[50px] min-w-[200px] hover:brightness-110 text-black rounded-sm border-none outline-none cursor-pointer flex-grow md:flex-grow-0 shadow-lg font-bold flex items-center justify-center px-8 transition-all">
                            <div className="flex items-center gap-3">
                                <RotateCcw size={18} className="group-hover:-rotate-90 transition-transform duration-500" strokeWidth={2.5} />
                                <span className="font-['Orbitron'] tracking-wide">继续播放</span>
                            </div>
                        </button>
                    )}

                    <button disabled={!hasResources} onClick={handlePlay} className={`flex-1 md:flex-none h-[50px] px-8 rounded-sm font-['Orbitron'] font-bold flex items-center justify-center gap-3 transition-all text-base group shadow-lg ${hasResources ? 'bg-white text-black hover:bg-gray-200' : 'bg-white/10 text-gray-500 cursor-not-allowed'}`} > 
                        <PlayCircle className={`w-5 h-5 ${hasResources ? 'text-black' : ''}`} /> 
                        <span>{loading ? '加载中...' : hasResources ? (resumeRecord ? '从头播放' : '播放') : '暂无资源'}</span> 
                    </button> 
                    
                    <button onClick={() => onToggleFavorite(fullMovieData)} className={`flex-none w-[50px] h-[50px] bg-black/40 backdrop-blur-sm border shadow-lg ${isFavorite ? 'border-accent text-accent bg-accent/10' : 'border-white/30 text-white hover:bg-white/10'} rounded-sm flex items-center justify-center transition-all`} title={isFavorite ? 'Remove from Vault' : 'Add to Vault'}> 
                        <Star className={`w-5 h-5 ${isFavorite ? 'fill-accent' : ''} transition-transform`} /> 
                    </button> 
                    <button onClick={handleRefreshMovie} className={`flex-none w-[50px] h-[50px] bg-black/40 backdrop-blur-sm border border-white/30 text-white hover:bg-white/10 hover:text-primary shadow-lg rounded-sm flex items-center justify-center transition-all`} title="轻量级同步信息"> 
                        <RefreshCw className={`w-5 h-5 ${isRefreshing ? 'animate-spin text-primary' : ''}`} /> 
                    </button>
                </div> 
                
                <div className="mb-10 relative"> 
                    <h3 className="text-xl font-bold text-white mb-3 drop-shadow-md">剧情简介</h3> 
                    <p className="text-gray-300 text-lg leading-relaxed font-sans max-w-4xl drop-shadow-md"> {displayData.overview || "暂无简介信息"} </p> 
                    
                    {fullMovieData.director && (
                        <div className="mt-6 text-gray-400">
                            <span className="mr-2">导演:</span>
                            <span className="text-white hover:underline cursor-pointer">{fullMovieData.director}</span>
                        </div>
                    )}
                </div>




            </div> 
        </div> 

        {/* Recommendations Section - Horizontal Scroll */}
        {recommendations.length > 0 && (
          <div className="mt-16 group">
            <div className="flex items-center justify-between mb-6 border-b border-white/10 pb-4">
               <h3 className="text-xl md:text-2xl font-['Orbitron'] font-bold text-white flex items-center gap-2">
                 <Sparkles className="text-accent" size={20} />
                 猜你喜欢
               </h3>
               <div className="flex gap-2">
                 <button onClick={() => scroll('left')} className="p-2 border border-white/10 hover:border-primary text-gray-400 hover:text-primary transition-colors bg-black/40"><ChevronLeft size={16} /></button>
                 <button onClick={() => scroll('right')} className="p-2 border border-white/10 hover:border-primary text-gray-400 hover:text-primary transition-colors bg-black/40"><ArrowRight size={16} /></button>
               </div>
            </div>
            
            <div ref={scrollRef} className="flex gap-4 overflow-x-auto no-scrollbar pb-8 pt-2" style={{ scrollSnapType: 'x mandatory' }}>
               {recommendations.map(movie => (
                 <div key={movie.id} className="w-40 md:w-52 flex-shrink-0 snap-start">
                    <MovieCard movie={movie} category={{ colorClass: 'border-white/20' }} onClick={onMovieSelect} hideRecommendationTag />
                 </div>
               ))}
            </div>
          </div>
        )}

    </div> 
  </div>); 
};