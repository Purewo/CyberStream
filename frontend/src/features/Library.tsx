import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Filter, Cpu,Globe, Calendar, AlertTriangle, Loader2, ScanLine } from 'lucide-react';
import { MovieCard } from '../components/movies/Cards';
import { Movie } from '../types';
import { FILTERS } from '../constants';
import { FilterTag } from '../components/ui/CyberComponents';
import { movieService, libraryService, systemService } from '../api';

// Mapping for API region names to Chinese
const REGION_NAME_MAP: Record<string, string> = {
  "United States of America": "美国",
  "United States": "美国",
  "United Kingdom": "英国",
  "China": "中国",
  "Japan": "日本",
  "South Korea": "韩国",
  "Korea": "韩国",
  "France": "法国",
  "Germany": "德国",
  "Canada": "加拿大",
  "Australia": "澳大利亚",
  "India": "印度",
  "Russia": "俄罗斯",
  "Thailand": "泰国",
  "Hong Kong": "中国香港",
  "Taiwan": "中国台湾",
  "Italy": "意大利",
  "Spain": "西班牙",
  "Brazil": "巴西",
  "Sweden": "瑞典",
  "Unknown": "未知",
  "Other": "其他"
};

// Mapping for API genre names to Chinese or UI display names
const GENRE_DISPLAY_MAP: Record<string, string> = {
  "Local": "本地"
};

export const Library = ({ onMovieSelect, initialType = "全部类型", activeLibraryId, onRequestBind }: { onMovieSelect: (m: Movie) => void; initialType?: string; activeLibraryId?: number | null; onRequestBind?: () => void }) => { 
  // Initial sort set to 'update_time' to match FILTERS constant ID
  const [filters, setFilters] = useState({ type: initialType, region: "全部地区", year: "全部年份", sort: "update_time" }); 
  const [libraryMovies, setLibraryMovies] = useState<Movie[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  useEffect(() => {
    const handleRefresh = () => {
      setPage(1);
      setRefreshTrigger(prev => prev + 1);
    };
    window.addEventListener('library-list-dirty', handleRefresh as EventListener);
    return () => window.removeEventListener('library-list-dirty', handleRefresh as EventListener);
  }, []);
  
  // Dynamic filter options fetched from backend
  const [filterOptions, setFilterOptions] = useState({
      genres: [] as string[],
      regions: [] as string[],
      years: [] as string[]
  });
  
  const observer = useRef<IntersectionObserver | null>(null);

  useEffect(() => { setFilters(prev => ({ ...prev, type: initialType })); }, [initialType]); 
  
  // Fetch global filters or library-specific filters
  useEffect(() => {
    const fetchFilters = async () => {
      try {
        let data;
        if (activeLibraryId && activeLibraryId !== -1) {
          data = await libraryService.getFilters(activeLibraryId);
        } else {
          data = await movieService.getGlobalFilters();
        }
        
        if (data) {
            let processedGenres = data.genres.map(g => g.name);

            // Filter out unwanted genres
            const unwantedGenres = ["电视电影", "音乐", "Sci-Fi & Fantasy", "动作冒险"];
            processedGenres = processedGenres.filter(g => !unwantedGenres.includes(g));

            // Move "Local" to the end if it exists
            const localIndex = processedGenres.indexOf("Local");
            if (localIndex !== -1) {
              processedGenres.splice(localIndex, 1);
              processedGenres.push("Local");
            }

            // Process regions to move "Unknown" to the end
            let processedRegions = data.countries.map(c => c.name);
            const unknownIndex = processedRegions.indexOf("Unknown");
            if (unknownIndex !== -1) {
                processedRegions.splice(unknownIndex, 1);
                processedRegions.push("Unknown");
            }

            // Process years: Filter unreasonable ones and limit length
            const currentYear = new Date().getFullYear();
            let processedYears = data.years.map(y => y.year);
            // Filter: Remove years too far in future or valid "bad data" like 20, 19
            processedYears = processedYears.filter(y => y >= 1880 && y <= currentYear + 1);
            // Sort descending
            processedYears.sort((a, b) => b - a);
            // Limit display length
            const MAX_YEARS_DISPLAY = 25;
            const displayedYears = processedYears.slice(0, MAX_YEARS_DISPLAY);

            setFilterOptions({
                genres: ["全部类型", ...processedGenres],
                regions: ["全部地区", ...processedRegions],
                years: ["全部年份", ...displayedYears.map(String), "更早"]
            });
        } else {
            // Fallback to static constants if API fails
            setFilterOptions({
                genres: FILTERS.types,
                regions: FILTERS.regions,
                years: FILTERS.years
            });
        }
      } catch (e) {
        console.error("Failed to fetch global filters", e);
        setFilterOptions({
            genres: FILTERS.types,
            regions: FILTERS.regions,
            years: FILTERS.years
        });
      }
    };
    fetchFilters();
  }, [activeLibraryId]);

  // Calculate dynamic page size
  useEffect(() => {
    const calculateSize = () => {
      const width = window.innerWidth;
      const cols = width >= 1280 ? 6 : width >= 1024 ? 5 : width >= 768 ? 4 : 2;
      const padding = width >= 768 ? 96 : 32; 
      const contentWidth = width - padding;
      const cardWidth = contentWidth / cols;
      const cardHeight = cardWidth * 1.5; 
      const rows = Math.ceil(window.innerHeight / cardHeight) + 1;
      const needed = cols * rows;
      setPageSize(Math.max(needed, 20));
    };
    calculateSize();
  }, []);

  // Reset list when filtering changes (EXCLUDING sort, as sort is local)
  useEffect(() => {
    setPage(1);
    setLibraryMovies([]);
    setHasMore(true);
  }, [filters.type, filters.region, filters.year, activeLibraryId, refreshTrigger]);

  // Fetch movies from Backend 
  useEffect(() => {
    if (pageSize === 0) return;
    let isActive = true;

    const fetchMovies = async () => {
      setIsLoading(true);
      try {
        // Map UI filter labels to API params
        let genreParam: string | undefined = undefined;
        if (filters.type !== "全部类型") {
           genreParam = filters.type;
        }

        // Use server-side sorting if possible for better consistency
        const sortBy = filters.sort; // rating, year, update_time (id used in FILTERS)
        const order = 'desc';
        
        let res;
        if (activeLibraryId && activeLibraryId !== -1) {
            res = await libraryService.getFilteredMovies(
                activeLibraryId,
                pageSize,
                page,
                genreParam,
                sortBy,
                order,
                filters.region,
                filters.year
            );
        } else {
            res = await movieService.getAll(
                pageSize, 
                page, 
                {
                  genre: genreParam,
                  sort_by: sortBy === 'update_time' ? 'date_added' : sortBy,
                  order: order,
                  country: filters.region !== '全部地区' ? filters.region : undefined,
                  year: filters.year !== '全部年份' ? filters.year : undefined
                }
            );
        }
        
        if (!isActive) return;
        
        setLibraryMovies(prev => {
          if (page === 1) return res.items;
          const existingIds = new Set(prev.map(m => m.id));
          const newItems = res.items.filter(m => !existingIds.has(m.id));
          return [...prev, ...newItems];
        });
        
        if (res.meta) {
          setHasMore(res.meta.current_page < res.meta.total_pages);
        } else {
          setHasMore(res.items.length === pageSize);
        }
      } catch (error) {
        if (!isActive) return;
        console.error("Failed to fetch library", error);
      } finally {
        if (isActive) setIsLoading(false);
      }
    };
    fetchMovies();
    return () => { isActive = false; };
  }, [page, pageSize, filters.type, filters.region, filters.year, filters.sort, activeLibraryId, refreshTrigger]); 

  // Infinite Scroll Ref
  const lastMovieRef = useCallback((node: HTMLDivElement) => {
    if (isLoading) return;
    if (observer.current) observer.current.disconnect();
    observer.current = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && hasMore) {
        setPage(prev => prev + 1);
      }
    });
    if (node) observer.current.observe(node);
  }, [isLoading, hasMore]);

  // Use directly since we now fetch already sorted from server
  const sortedMovies = libraryMovies;

  return (
    <div className="min-h-screen w-full pt-24 px-4 md:px-12 pb-12"> 
      <div className="flex items-center gap-4 mb-8"> 
        <div className="p-2 border border-primary text-primary shadow-[0_0_10px_var(--color-primary)]"> <Filter className="w-6 h-6" /> </div> 
        <h1 className="text-3xl font-['Orbitron'] font-bold text-white tracking-widest flex items-center gap-4"> 
           <span>DATABASE <span className="text-primary">ARCHIVES</span></span>
        </h1> 
        <div className="flex-[0.1] h-[1px] bg-gradient-to-r from-primary/50 to-transparent"></div> 
        {activeLibraryId && activeLibraryId !== -1 && (
          <button 
            onClick={async () => {
              const res = await libraryService.scanLibrary(activeLibraryId);
              if (res) {
                 window.dispatchEvent(new CustomEvent("cyber:scan:started"));
              } else {
                 alert('扫描启动失败');
              }
            }}
            className="flex items-center gap-2 px-4 py-2 bg-primary/10 border border-primary/50 text-primary hover:bg-primary/30 text-sm font-bold tracking-widest transition-colors font-mono uppercase"
          >
             <ScanLine size={16} /> 扫描本库
          </button>
        )}
        <div className="flex-grow h-[1px] bg-gradient-to-l from-primary/50 to-transparent"></div> 
      </div> 
      
      {/* Filter Control Panel (Inline) */}
      <div className="bg-[#0a0a12]/80 border border-white/10 backdrop-blur-md p-6 mb-10 relative overflow-hidden group tech-border"> 
        <div className="absolute top-0 right-0 w-16 h-16 border-t-2 border-r-2 border-red-500/50"></div> 
        <div className="space-y-4 relative z-10"> 
          {/* Genre Filter */}
          <div className="flex flex-col md:flex-row md:items-start gap-2 md:gap-4"> 
            <span className="text-primary font-['Noto_Sans_SC'] font-bold py-1 min-w-[4rem] flex items-center gap-2 mt-1"> <Cpu size={14} /> 类型 </span> 
            <div className="flex flex-wrap gap-2"> {filterOptions.genres.map(type => (<FilterTag key={type} label={GENRE_DISPLAY_MAP[type] || type} active={filters.type === type} onClick={() => setFilters({ ...filters, type: type })} />))} </div> 
          </div> 
          <div className="h-[1px] bg-white/5 w-full"></div> 
          
          {/* Region Filter */}
          <div className="flex flex-col md:flex-row md:items-start gap-2 md:gap-4"> 
            <span className="text-secondary font-['Noto_Sans_SC'] font-bold py-1 min-w-[4rem] flex items-center gap-2 mt-1"> <Globe size={14} /> 地区 </span> 
            <div className="flex flex-wrap gap-2"> 
              {filterOptions.regions.map(region => (
                <FilterTag 
                  key={region} 
                  label={REGION_NAME_MAP[region] || region} 
                  active={filters.region === region} 
                  onClick={() => setFilters({ ...filters, region: region })} 
                />
              ))} 
            </div> 
          </div> 
          <div className="h-[1px] bg-white/5 w-full"></div> 
          
          {/* Year Filter */}
          <div className="flex flex-col md:flex-row md:items-start gap-2 md:gap-4"> 
            <span className="text-accent font-['Noto_Sans_SC'] font-bold py-1 min-w-[4rem] flex items-center gap-2 mt-1"> <Calendar size={14} /> 年份 </span> 
            <div className="flex flex-wrap gap-2"> {filterOptions.years.map(year => (<FilterTag key={year} label={year} active={filters.year === year} onClick={() => setFilters({ ...filters, year: year })} />))} </div> 
          </div> 
        </div> 
      </div> 
      
      {/* List Header */}
      <div className="flex flex-col md:flex-row justify-between items-end md:items-center mb-6 font-['Rajdhani'] gap-4"> 
        <div className="text-gray-400 text-sm flex items-center gap-2"> 
          当前展示 <span className="text-primary font-bold text-lg">{sortedMovies.length}</span> 个资源
          {filters.region !== "全部地区" || filters.year !== "全部年份" ? (
             <span className="text-xs text-orange-400 border border-orange-500/30 px-1 rounded ml-2">筛选已生效</span>
          ) : null}
        </div> 
        {/* Sort Buttons (Local Sort) */}
        <div className="flex items-center gap-2 bg-black/40 border border-white/10 px-2 py-1 rounded-sm"> 
          {FILTERS.sorts.map(sort => (
            <button 
              key={sort.id} 
              onClick={() => setFilters({ ...filters, sort: sort.id })} 
              className={`px-3 py-1 text-sm flex items-center gap-1 hover:text-primary transition-colors relative ${filters.sort === sort.id ? 'text-primary font-bold' : 'text-gray-500'}`} 
            > 
              {sort.label} 
              {filters.sort === sort.id && <div className="absolute bottom-0 left-0 w-full h-[2px] bg-primary shadow-[0_0_5px_var(--color-primary)]"></div>} 
            </button>
          ))} 
        </div> 
      </div> 
      
      {/* Movie Grid using sortedMovies */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-2 md:gap-4 justify-center"> 
        {sortedMovies.map((movie, index) => {
           if (index === sortedMovies.length - 1) {
             return <div key={movie.id} ref={lastMovieRef}><MovieCard movie={movie} category={{ colorClass: 'border-white/20' }} onClick={onMovieSelect} /></div>;
           }
           return <MovieCard key={movie.id} movie={movie} category={{ colorClass: 'border-white/20' }} onClick={onMovieSelect} />;
        })} 
      </div>
      
      {isLoading && (
        <div className="w-full flex flex-col items-center justify-center py-8 gap-2">
          <Loader2 className="w-8 h-8 text-primary animate-spin" />
          <span className="text-xs font-['Orbitron'] text-primary animate-pulse">正在扫描归档...</span>
        </div>
      )}

      {!isLoading && sortedMovies.length === 0 && (
        <div className="h-96 w-full flex flex-col items-center justify-center gap-4 text-gray-600 border border-white/5 bg-black/20"> 
          <AlertTriangle size={48} className="opacity-30" /> 
          <div className="font-['Orbitron'] tracking-widest text-xl">无匹配数据</div> 
          <div className="text-xs font-sans text-center">
            当前筛选条件下未找到相关资源
          </div> 
          {activeLibraryId && onRequestBind && (
            <button 
              onClick={onRequestBind}
              className="mt-4 px-6 py-2 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 font-['Orbitron'] text-sm tracking-wider transition-all"
            >
              绑定存储路径
            </button>
          )}
        </div>
      )}
      
      {!hasMore && sortedMovies.length > 0 && (
        <div className="w-full text-center py-8 text-gray-600 font-['Rajdhani'] text-xs tracking-widest">已加载全部资源</div>
      )}
    </div>
  ); 
};