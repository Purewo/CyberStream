import React, { useRef, useState, useEffect } from 'react';
import { Cpu, Zap, Heart, Monitor, ChevronRight, Play, Film } from 'lucide-react';
import { MovieCard } from '../components/movies/Cards';
import { Movie, Category } from '../types';
import { FEATURED_MOVIE } from '../constants';
import { homeService, movieService } from '../api';

const DEFAULT_CATEGORY_ICONS: Record<string, { icon: React.ReactNode, colorClass: string, bgClass: string }> = {
  'sci_fi': { icon: <Cpu className="w-5 h-5" />, colorClass: 'border-primary text-primary', bgClass: 'bg-primary/10' },
  'action': { icon: <Zap className="w-5 h-5" />, colorClass: 'border-red-500 text-red-500', bgClass: 'bg-red-500/10' },
  'drama': { icon: <Heart className="w-5 h-5" />, colorClass: 'border-secondary text-secondary', bgClass: 'bg-secondary/10' },
  'anime': { icon: <Monitor className="w-5 h-5" />, colorClass: 'border-accent text-accent', bgClass: 'bg-accent/10' },
};

const getCategoryStyle = (key: string, title: string) => {
  if (DEFAULT_CATEGORY_ICONS[key]) return DEFAULT_CATEGORY_ICONS[key];
  return { icon: <Film className="w-5 h-5" />, colorClass: 'border-gray-400 text-gray-400', bgClass: 'bg-gray-400/10' };
};

let cachedHomepageData: { hero: Movie | null, sections: any[] } | null = null;

const CategoryRow: React.FC<{ section: any; onMovieSelect: (m: Movie) => void; onViewMore: (id: string) => void }> = ({ section, onMovieSelect, onViewMore }) => { 
  const scrollRef = useRef<HTMLDivElement>(null); 
  const scroll = (direction: 'left' | 'right') => { 
    if (scrollRef.current) { 
      const { current } = scrollRef; 
      const scrollAmount = direction === 'left' ? -500 : 500; 
      current.scrollBy({ left: scrollAmount, behavior: 'smooth' }); 
    } 
  }; 
  const moviesToRender = Array.isArray(section.items) ? section.items : []; 
  if (moviesToRender.length === 0) return null; 

  const style = getCategoryStyle(section.key, section.title);

  return (
    <div className="mb-16 mt-8 relative z-10 px-4 md:px-12 group"> 
      <div className="flex items-center justify-between mb-4 border-b border-white/10 pb-2"> 
        <div className="flex items-center gap-3"> 
          <div className={`p-1 border rounded-sm shadow-[0_0_10px_currentColor] ${style.colorClass}`}>{style.icon}</div> 
          <h2 className={`text-2xl font-['Orbitron'] font-bold tracking-wider text-white uppercase hover:text-primary transition-all duration-300`}>{section.title}</h2> 
        </div> 
        <button onClick={() => onViewMore(section.genre || section.title)} className="flex items-center gap-1 text-sm font-['Rajdhani'] font-bold text-gray-500 hover:text-primary transition-colors tracking-widest group/btn">查看全部 <ChevronRight size={14} className="group-hover/btn:translate-x-1 transition-transform" /></button> 
      </div> 
      <div className="relative w-full hidden md:block h-[1px] bg-gradient-to-r from-white/20 to-transparent mb-4"></div> 
      <button onClick={() => scroll('left')} className="absolute left-0 top-1/2 -translate-y-1/2 z-30 h-full w-16 bg-gradient-to-r from-black to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-start pl-2 text-white hover:text-primary"><div className="bg-black/50 p-2 border border-white/20 backdrop-blur-sm hover:border-primary">&lt;</div></button> 
      <button onClick={() => scroll('right')} className="absolute right-0 top-1/2 -translate-y-1/2 z-30 h-full w-16 bg-gradient-to-l from-black to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-end pr-2 text-white hover:text-primary"><div className="bg-black/50 p-2 border border-white/20 backdrop-blur-sm hover:border-primary">&gt;</div></button> 
      <div ref={scrollRef} className="flex gap-2 overflow-x-auto no-scrollbar pb-8 pt-4" style={{ scrollSnapType: 'x mandatory' }}> 
        {moviesToRender.map((movie: Movie) => (<div key={movie.id} className="w-36 md:w-48 flex-shrink-0"><MovieCard movie={movie} category={{ colorClass: style.colorClass }} onClick={onMovieSelect} /></div>))} 
      </div> 
    </div>
  ); 
};

export const Home = ({ onMovieSelect, onViewMore }: { onMovieSelect: (m: Movie) => void; onViewMore: (id: string) => void }) => { 
  const [heroMovie, setHeroMovie] = useState<Movie>(() => {
     if (cachedHomepageData && cachedHomepageData.hero) return cachedHomepageData.hero;
     return FEATURED_MOVIE;
  });
  
  const [sections, setSections] = useState<any[]>(cachedHomepageData?.sections || []);

  useEffect(() => {
    if (cachedHomepageData) return;

    const fetchHomepageData = async () => {
      try {
        const data = await homeService.getHomepage();
        if (data) {
          const hero = data.hero?.movie ? movieService.flattenMovies([data.hero.movie])[0] : FEATURED_MOVIE;
          
          const mappedSections = (data.sections || []).map(sec => ({
            ...sec,
            items: movieService.flattenMovies(sec.items || [])
          }));

          setHeroMovie(hero);
          setSections(mappedSections);
          cachedHomepageData = { hero, sections: mappedSections };
        } else {
          // Fallback if the API is not available
          console.warn("Homepage API returned null. Falling back to default featured movie.");
          setHeroMovie(FEATURED_MOVIE);
        }
      } catch (err) {
        console.error("Home initialization failed", err);
      }
    };
    fetchHomepageData();
  }, []);

  return (
    <> 
      <div className="relative w-full h-[85vh] overflow-hidden flex items-center z-10 transition-all duration-700 group"> 
        <div className="absolute inset-0 bg-[#0a0a12]">
             {/* Dynamic Background Image */}
             <div 
                className="absolute inset-0 bg-cover bg-center transition-opacity duration-1000 opacity-80"
                style={{ backgroundImage: `url('${heroMovie?.backdrop_url || heroMovie?.cover_url || "https://images.unsplash.com/photo-1535868463750-c78d9543614f?q=80&w=2676&auto=format&fit=crop"}')` }}
             ></div>
             {/* Gradient Overlay */}
             <div className="absolute inset-0 bg-gradient-to-t from-[#050505] via-[#050505]/40 to-transparent"></div>
             <div className="absolute inset-0 bg-gradient-to-r from-[#050505] via-[#050505]/60 to-transparent"></div>
        </div> 
        
        <div className="container mx-auto px-6 md:px-12 relative mt-20 z-20"> 
          <div className="max-w-4xl">
              <h1 className="text-6xl md:text-8xl font-black font-['Orbitron'] text-white mb-6 tracking-tighter glitch-text leading-tight drop-shadow-2xl" data-text={heroMovie?.title || "CYBERSTREAM"}>
                  {heroMovie?.title || "CYBERSTREAM"}
              </h1> 
              
              <div className="flex flex-col gap-6 max-w-2xl">
                  {/* Clean text display */}
                  <div className="relative pl-6">
                      <div className="absolute left-0 top-1 bottom-1 w-1 bg-primary shadow-[0_0_15px_var(--color-primary)]"></div>
                      <p className="text-gray-200 text-lg md:text-xl leading-relaxed font-sans drop-shadow-lg line-clamp-5 text-shadow-sm opacity-90">
                          {heroMovie?.desc || heroMovie?.overview || "Connect. Stream. Transcend."}
                      </p>
                  </div>
                  
                  <button onClick={() => heroMovie && onMovieSelect(heroMovie)} className="w-fit border-2 border-primary bg-primary/10 hover:bg-primary text-primary hover:text-black px-8 py-4 rounded-sm font-['Orbitron'] font-bold flex items-center gap-3 transition-all hover:scale-105 shadow-[0_0_15px_var(--color-primary)] hover:shadow-[0_0_30px_var(--color-primary)] group/btn backdrop-blur-sm">
                      <Play className="w-5 h-5 fill-primary group-hover/btn:fill-black transition-colors" />
                      <span className="tracking-wider">启动系统 [START]</span>
                  </button> 
              </div>
          </div>
        </div> 
      </div> 
      <div className="relative -mt-20 pb-10 space-y-8 z-20"> 
        {sections.map(sec => (
          <CategoryRow 
            key={sec.key || sec.title} 
            section={sec}
            onMovieSelect={onMovieSelect} 
            onViewMore={onViewMore} 
          />
        ))} 
      </div> 
    </>
  ); 
};