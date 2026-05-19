import React, { useState } from 'react';
import { Play, Star, ArrowUp, ArrowDown, Minus, Crown, Trophy, Check, Eye, Database, AlertTriangle } from 'lucide-react';
import { Movie } from '../../types';
import { TechBadge } from '../ui/CyberComponents';

interface MovieCardProps {
  movie: Movie;
  category?: { colorClass?: string };
  onClick: (movie: Movie) => void;
  hideRecommendationTag?: boolean;
}

export const MovieCard: React.FC<MovieCardProps> = ({ movie, onClick, hideRecommendationTag }) => { 
  const [isHovered, setIsHovered] = useState(false); 
  if (!movie) return null;
  const safeId = String(movie.id || 'def');
  const tech = movie.tech_specs || {};
  let resLabel = (tech.resolution && tech.resolution.toUpperCase() !== 'UNKNOWN') ? String(tech.resolution) : null;
  if (!resLabel && movie.tags && Array.isArray(movie.tags)) {
    if (movie.tags.includes('4K') || tech.flag_is_4k) resLabel = '4K';
    else if (movie.tags.includes('1080P')) resLabel = '1080P';
    else if (movie.tags.includes('720P')) resLabel = '720P';
  }
  const codecLabel = (tech.codec && tech.codec.toUpperCase() !== 'UNKNOWN') ? String(tech.codec) : '';
  
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    window.dispatchEvent(new CustomEvent('show-movie-context-menu', {
      detail: { x: e.clientX, y: e.clientY, movie }
    }));
  };

  return (
    <div onContextMenu={handleContextMenu} onClick={() => onClick(movie)} className={`relative flex-shrink-0 w-full max-w-[220px] mx-auto aspect-[2/3] transition-all duration-300 ease-out cursor-pointer group ${isHovered ? 'scale-105 z-20' : 'scale-100 z-10'}`} onMouseEnter={() => setIsHovered(true)} onMouseLeave={() => setIsHovered(false)}> 
      <div className={`absolute -inset-0.5 bg-gradient-to-r from-transparent via-white/20 to-transparent opacity-0 group-hover:opacity-100 transition duration-500 blur`}></div>
      <div className={`h-full w-full bg-[#0a0a12] border border-white/10 relative overflow-hidden ${isHovered ? `border-primary shadow-[0_0_15px_var(--color-primary)]` : ''}`}> 
        {movie.cover_url ? (
            <img src={movie.cover_url} alt={movie.title} referrerPolicy="no-referrer" className="absolute inset-0 w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity" />
        ) : (
            <div className="absolute inset-0 opacity-30 flex flex-col items-center justify-center bg-gradient-to-br from-[#1a1a20] to-black"> 
                <div className="text-6xl font-black text-white/10 group-hover:text-primary/20 font-['Orbitron'] transition-colors duration-300">{movie.title?.charAt(0) || 'M'}</div> 
            </div>
        )} 
        {!movie.cover_url && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-4 pointer-events-none"> 
                <div className={`font-['Orbitron'] font-bold text-lg md:text-xl tracking-tighter opacity-80 group-hover:text-primary group-hover:animate-pulse break-all line-clamp-3`}>{movie.title}</div> 
                <div className="text-[10px] md:text-xs text-gray-500 mt-2 font-['Rajdhani'] tracking-widest">{safeId.toUpperCase().substring(0, 8)}...</div> 
            </div>
        )} 
        
        {/* Left Side: Played Pennant/Banner */}

        {/* Top Left Badges: Status and Sources */}
        <div className={`absolute z-10 flex flex-col gap-1 items-start top-2 left-2`}>
            {movie.isUnscraped && (
               <div className="flex items-center gap-1 bg-red-950/90 text-red-500 text-[10px] font-bold px-1.5 py-0.5 rounded border border-red-500/50 shadow-[0_0_10px_rgba(239,68,68,0.2)]">
                  <AlertTriangle size={10} />
                  <span className="tracking-wider">RAW</span>
               </div>
            )}
            {movie.recommendation && !hideRecommendationTag && (
               <div className="flex items-center gap-1 bg-secondary/90 text-black text-[10px] font-bold px-1.5 py-0.5 rounded border border-secondary shadow-[0_0_10px_rgba(var(--color-secondary-rgb),0.2)]">
                  <Star size={10} />
                  <span className="tracking-wider">{movie.recommendation.primary_reason?.label || movie.recommendation.reason_text || '推荐'}</span>
               </div>
            )}
        </div>

        {/* Top Right Badges (Tech Specs) */}
        <div className={`absolute top-2 right-2 z-30 flex flex-col gap-1 items-end transition-all duration-300 transform ${isHovered ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-4'}`}> 
          {movie.quality_badge && (
              <TechBadge className="bg-black/80 text-primary border-primary/50 uppercase font-bold shadow-[0_0_10px_rgba(var(--color-primary-rgb),0.2)]">
                  {movie.quality_badge}
              </TechBadge>
          )}
          {resLabel && <TechBadge className="bg-black/80 text-primary border-primary/50 uppercase">{resLabel}</TechBadge>} 
          {tech.flag_is_remux && <TechBadge className="bg-black/80 text-primary border-primary/50 uppercase">REMUX</TechBadge>}
          {tech.flag_is_dolby_vision && <TechBadge className="bg-black/80 text-primary border-primary/50 uppercase">DV</TechBadge>}
          {!tech.flag_is_dolby_vision && tech.flag_is_hdr && <TechBadge className="bg-black/80 text-primary border-primary/50 uppercase">HDR</TechBadge>}
          {tech.audio_is_atmos && <TechBadge className="bg-black/80 text-primary border-primary/50 uppercase">ATMOS</TechBadge>}
          {codecLabel && <TechBadge className="bg-black/80 text-primary/70 border-primary/30 uppercase">{codecLabel}</TechBadge>} 
        </div> 

        <div className={`absolute inset-0 bg-black/90 flex flex-col justify-end p-3 transition-opacity duration-300 ${isHovered ? 'opacity-100' : 'opacity-0'}`}> 
          <h3 className="text-white font-['Orbitron'] text-xs font-bold truncate text-primary">{movie.title}</h3> 
          <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-300 font-['Rajdhani']"> 
            {resLabel && <span className="px-1 border border-primary text-primary bg-primary/10">{resLabel}</span>}
            <span>{movie.year}</span> 
            <span className="text-secondary">{movie.rating}</span> 
          </div> 
          <button className="w-full mt-2 bg-primary text-black text-[10px] font-bold py-1 hover:bg-white transition-colors flex items-center justify-center gap-1"><Play size={10} fill="black" /> PLAY</button> 
        </div> 
      </div> 
    </div>
  ); 
};

interface RankStyle {
  color: string;
  border: string;
  shadow: string;
  icon?: React.ReactNode;
}

export const TopCard: React.FC<{ movie: Movie; rank: number; style: RankStyle; onClick: (m: Movie) => void }> = ({ movie, rank, style, onClick }) => {
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    window.dispatchEvent(new CustomEvent('show-movie-context-menu', {
      detail: { x: e.clientX, y: e.clientY, movie }
    }));
  };
  return (
  <div onContextMenu={handleContextMenu} onClick={() => onClick(movie)} className={`relative group cursor-pointer transition-transform hover:scale-105 max-w-[200px] mx-auto w-full`}> 
    {rank === 1 && (<div className="absolute -top-10 left-1/2 -translate-x-1/2 animate-bounce">{style.icon}</div>)} 
    <div className={`aspect-[2/3] w-full bg-black border-2 ${style.border} relative overflow-hidden ${style.shadow}`}> 
      <div className="absolute top-0 left-0 w-12 h-12 bg-black/80 backdrop-blur flex items-center justify-center border-r border-b border-white/20 z-20 font-['Orbitron'] font-black text-2xl" style={{ color: style.color }}>{rank}</div> 
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/90 z-10"></div> 
      <div className="absolute inset-0 opacity-50" style={{ backgroundImage: `radial-gradient(circle at 50% 50%, ${style.color}40, transparent)` }}></div> 
      {movie.cover_url ? (
          <img src={movie.cover_url} alt={movie.title} referrerPolicy="no-referrer" className="absolute inset-0 w-full h-full object-cover opacity-60" />
      ) : (
          <div className="absolute inset-0 flex items-center justify-center"><span className="text-6xl font-['Orbitron'] font-bold opacity-10 text-white">{movie.title.charAt(0)}</span></div>
      )} 
      <div className="absolute bottom-0 left-0 w-full p-4 z-20"> 
        <h3 className="text-white font-['Orbitron'] font-bold truncate mb-1 group-hover:text-primary transition-colors">{movie.title}</h3> 
        <div className="flex items-center justify-between text-sm font-['Rajdhani']"><span className="text-gray-400">{movie.views}</span><span className="font-bold flex items-center gap-1" style={{ color: style.color }}><Star size={12} fill="currentColor" /> {movie.rating}</span></div> 
      </div> 
    </div> 
  </div>
  );
};

export const RankRow: React.FC<{ movie: Movie; rank: number; onClick: (m: Movie) => void }> = ({ movie, rank, onClick }) => { 
  const getTrendIcon = (trend?: string) => { 
    if (trend === 'up') return <ArrowUp size={14} className="text-primary" />; 
    if (trend === 'down') return <ArrowDown size={14} className="text-red-500" />; 
    return <Minus size={14} className="text-gray-500" />; 
  }; 
  
  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    window.dispatchEvent(new CustomEvent('show-movie-context-menu', {
      detail: { x: e.clientX, y: e.clientY, movie }
    }));
  };

  return (
    <div onContextMenu={handleContextMenu} onClick={() => onClick(movie)} className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-white/5 transition-colors border-b border-white/5 group cursor-pointer"> 
      <div className="col-span-1 text-center font-['Orbitron'] font-bold text-xl text-gray-600 group-hover:text-white transition-colors">{rank < 10 ? `0${rank}` : rank}</div> 
      <div className="col-span-1"> 
        <div className="w-10 h-14 bg-gray-800 border border-white/10 overflow-hidden"> 
          {movie.cover_url && <img src={movie.cover_url} referrerPolicy="no-referrer" className="w-full h-full object-cover opacity-80" alt="" />} 
        </div> 
      </div> 
      <div className="col-span-5 md:col-span-6"><h4 className="text-white font-['Noto_Sans_SC'] font-bold truncate group-hover:text-primary transition-colors">{movie.title}</h4><span className="text-xs text-gray-500 font-['Rajdhani']">{movie.year}</span></div> 
      <div className="col-span-2 text-center font-['Rajdhani'] font-bold text-secondary">{movie.rating}</div> 
      <div className="col-span-2 flex justify-center items-center gap-1 text-xs font-['Rajdhani'] text-gray-400">{getTrendIcon(movie.trend)}{movie.trend !== 'stable' && <span>{movie.change}</span>}</div> 
      <div className="col-span-1 text-center text-xs font-['Rajdhani'] text-gray-500 hidden md:block">{movie.views}</div> 
    </div>
  ); 
};

export const getRankStyle = (rank: number): RankStyle => { 
  if (rank === 1) return { color: '#f2ff00', border: 'border-[#f2ff00]', shadow: 'shadow-[0_0_20px_#f2ff00]', icon: <Crown size={24} className="fill-[#f2ff00] text-[#f2ff00]" /> }; 
  if (rank === 2) return { color: '#00f3ff', border: 'border-[#00f3ff]', shadow: 'shadow-[0_0_20px_#00f3ff]', icon: <Trophy size={20} className="text-[#00f3ff]" /> }; 
  if (rank === 3) return { color: '#bc13fe', border: 'border-[#bc13fe]', shadow: 'shadow-[0_0_20px_#bc13fe]', icon: <Trophy size={20} className="text-[#bc13fe]" /> }; 
  return { color: 'white', border: 'border-white/20', shadow: '' }; 
};