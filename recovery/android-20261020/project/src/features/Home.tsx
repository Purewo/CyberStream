import React, { useRef, useState, useEffect } from 'react';
import {
  Cpu, Zap, Heart, Drama, Monitor, ChevronRight, Play, Film,
  Swords, Compass, Search, Skull, Wand2, Crosshair, Music,
  Smile, Ghost, Rocket, Trophy, Baby, History, FileText, Camera, Tv,
  HardDrive, Sparkles,
} from 'lucide-react';
import { MovieCard } from '../components/movies/Cards';
import { Movie, Category } from '../types';
import { FEATURED_MOVIE } from '../constants';
import { homeService, movieService } from '../api';

type CategoryStyle = { icon: React.ReactNode; colorClass: string; bgClass: string };

// 主流类型 → 图标 / 颜色映射。后端 section.key 可能是英文 slug（sci_fi、action…）
// 也可能是中文（科幻、动作…），section.title 也可能是中文标签——map 同时挂上几种
// 别名，匹配时按 key → title 顺序找。
const DEFAULT_CATEGORY_ICONS: Record<string, CategoryStyle> = {
  // 科幻
  sci_fi:    { icon: <Cpu     className="w-5 h-5" />, colorClass: 'border-primary text-primary', bgClass: 'bg-primary/10' },
  scifi:     { icon: <Cpu     className="w-5 h-5" />, colorClass: 'border-primary text-primary', bgClass: 'bg-primary/10' },
  '科幻':    { icon: <Cpu     className="w-5 h-5" />, colorClass: 'border-primary text-primary', bgClass: 'bg-primary/10' },
  // 动作
  action:    { icon: <Zap     className="w-5 h-5" />, colorClass: 'border-red-500 text-red-500', bgClass: 'bg-red-500/10' },
  '动作':    { icon: <Zap     className="w-5 h-5" />, colorClass: 'border-red-500 text-red-500', bgClass: 'bg-red-500/10' },
  // 剧情：戏剧面具 icon
  drama:     { icon: <Drama   className="w-5 h-5" />, colorClass: 'border-secondary text-secondary', bgClass: 'bg-secondary/10' },
  '剧情':    { icon: <Drama   className="w-5 h-5" />, colorClass: 'border-secondary text-secondary', bgClass: 'bg-secondary/10' },
  // 爱情：心
  romance:   { icon: <Heart   className="w-5 h-5" />, colorClass: 'border-pink-500 text-pink-500', bgClass: 'bg-pink-500/10' },
  '爱情':    { icon: <Heart   className="w-5 h-5" />, colorClass: 'border-pink-500 text-pink-500', bgClass: 'bg-pink-500/10' },
  // 动画
  anime:     { icon: <Monitor className="w-5 h-5" />, colorClass: 'border-accent text-accent', bgClass: 'bg-accent/10' },
  animation: { icon: <Monitor className="w-5 h-5" />, colorClass: 'border-accent text-accent', bgClass: 'bg-accent/10' },
  '动画':    { icon: <Monitor className="w-5 h-5" />, colorClass: 'border-accent text-accent', bgClass: 'bg-accent/10' },
  // 战争
  war:       { icon: <Swords  className="w-5 h-5" />, colorClass: 'border-amber-700 text-amber-600', bgClass: 'bg-amber-700/10' },
  '战争':    { icon: <Swords  className="w-5 h-5" />, colorClass: 'border-amber-700 text-amber-600', bgClass: 'bg-amber-700/10' },
  // 冒险
  adventure: { icon: <Compass className="w-5 h-5" />, colorClass: 'border-orange-400 text-orange-400', bgClass: 'bg-orange-400/10' },
  '冒险':    { icon: <Compass className="w-5 h-5" />, colorClass: 'border-orange-400 text-orange-400', bgClass: 'bg-orange-400/10' },
  // 悬疑
  mystery:   { icon: <Search  className="w-5 h-5" />, colorClass: 'border-indigo-400 text-indigo-400', bgClass: 'bg-indigo-400/10' },
  '悬疑':    { icon: <Search  className="w-5 h-5" />, colorClass: 'border-indigo-400 text-indigo-400', bgClass: 'bg-indigo-400/10' },
  // 惊悚
  thriller:  { icon: <Crosshair className="w-5 h-5" />, colorClass: 'border-red-400 text-red-400', bgClass: 'bg-red-400/10' },
  '惊悚':    { icon: <Crosshair className="w-5 h-5" />, colorClass: 'border-red-400 text-red-400', bgClass: 'bg-red-400/10' },
  // 恐怖
  horror:    { icon: <Skull   className="w-5 h-5" />, colorClass: 'border-zinc-300 text-zinc-300', bgClass: 'bg-zinc-700/30' },
  '恐怖':    { icon: <Skull   className="w-5 h-5" />, colorClass: 'border-zinc-300 text-zinc-300', bgClass: 'bg-zinc-700/30' },
  // 犯罪
  crime:     { icon: <Skull   className="w-5 h-5" />, colorClass: 'border-yellow-600 text-yellow-600', bgClass: 'bg-yellow-600/10' },
  '犯罪':    { icon: <Skull   className="w-5 h-5" />, colorClass: 'border-yellow-600 text-yellow-600', bgClass: 'bg-yellow-600/10' },
  // 奇幻
  fantasy:   { icon: <Wand2   className="w-5 h-5" />, colorClass: 'border-purple-400 text-purple-400', bgClass: 'bg-purple-400/10' },
  '奇幻':    { icon: <Wand2   className="w-5 h-5" />, colorClass: 'border-purple-400 text-purple-400', bgClass: 'bg-purple-400/10' },
  // 喜剧
  comedy:    { icon: <Smile   className="w-5 h-5" />, colorClass: 'border-yellow-400 text-yellow-400', bgClass: 'bg-yellow-400/10' },
  '喜剧':    { icon: <Smile   className="w-5 h-5" />, colorClass: 'border-yellow-400 text-yellow-400', bgClass: 'bg-yellow-400/10' },
  // 音乐 / 歌舞
  music:     { icon: <Music   className="w-5 h-5" />, colorClass: 'border-fuchsia-400 text-fuchsia-400', bgClass: 'bg-fuchsia-400/10' },
  musical:   { icon: <Music   className="w-5 h-5" />, colorClass: 'border-fuchsia-400 text-fuchsia-400', bgClass: 'bg-fuchsia-400/10' },
  '音乐':    { icon: <Music   className="w-5 h-5" />, colorClass: 'border-fuchsia-400 text-fuchsia-400', bgClass: 'bg-fuchsia-400/10' },
  '歌舞':    { icon: <Music   className="w-5 h-5" />, colorClass: 'border-fuchsia-400 text-fuchsia-400', bgClass: 'bg-fuchsia-400/10' },
  // 灵异 / 超自然
  supernatural: { icon: <Ghost className="w-5 h-5" />, colorClass: 'border-violet-400 text-violet-400', bgClass: 'bg-violet-400/10' },
  '灵异':    { icon: <Ghost   className="w-5 h-5" />, colorClass: 'border-violet-400 text-violet-400', bgClass: 'bg-violet-400/10' },
  // 太空 / 末日
  space:     { icon: <Rocket  className="w-5 h-5" />, colorClass: 'border-cyan-400 text-cyan-400', bgClass: 'bg-cyan-400/10' },
  // 体育
  sport:     { icon: <Trophy  className="w-5 h-5" />, colorClass: 'border-emerald-400 text-emerald-400', bgClass: 'bg-emerald-400/10' },
  sports:    { icon: <Trophy  className="w-5 h-5" />, colorClass: 'border-emerald-400 text-emerald-400', bgClass: 'bg-emerald-400/10' },
  '体育':    { icon: <Trophy  className="w-5 h-5" />, colorClass: 'border-emerald-400 text-emerald-400', bgClass: 'bg-emerald-400/10' },
  // 家庭 / 儿童
  family:    { icon: <Baby    className="w-5 h-5" />, colorClass: 'border-teal-400 text-teal-400', bgClass: 'bg-teal-400/10' },
  kids:      { icon: <Baby    className="w-5 h-5" />, colorClass: 'border-teal-400 text-teal-400', bgClass: 'bg-teal-400/10' },
  '家庭':    { icon: <Baby    className="w-5 h-5" />, colorClass: 'border-teal-400 text-teal-400', bgClass: 'bg-teal-400/10' },
  '儿童':    { icon: <Baby    className="w-5 h-5" />, colorClass: 'border-teal-400 text-teal-400', bgClass: 'bg-teal-400/10' },
  // 历史 / 古装
  history:   { icon: <History className="w-5 h-5" />, colorClass: 'border-amber-400 text-amber-400', bgClass: 'bg-amber-400/10' },
  '历史':    { icon: <History className="w-5 h-5" />, colorClass: 'border-amber-400 text-amber-400', bgClass: 'bg-amber-400/10' },
  '古装':    { icon: <History className="w-5 h-5" />, colorClass: 'border-amber-400 text-amber-400', bgClass: 'bg-amber-400/10' },
  // 纪录片
  documentary: { icon: <FileText className="w-5 h-5" />, colorClass: 'border-stone-300 text-stone-300', bgClass: 'bg-stone-500/10' },
  '纪录片':  { icon: <FileText className="w-5 h-5" />, colorClass: 'border-stone-300 text-stone-300', bgClass: 'bg-stone-500/10' },
  // 传记
  biography: { icon: <Camera  className="w-5 h-5" />, colorClass: 'border-rose-400 text-rose-400', bgClass: 'bg-rose-400/10' },
  '传记':    { icon: <Camera  className="w-5 h-5" />, colorClass: 'border-rose-400 text-rose-400', bgClass: 'bg-rose-400/10' },
  // 综艺 / TV
  tv:        { icon: <Tv      className="w-5 h-5" />, colorClass: 'border-sky-400 text-sky-400', bgClass: 'bg-sky-400/10' },
  variety:   { icon: <Tv      className="w-5 h-5" />, colorClass: 'border-sky-400 text-sky-400', bgClass: 'bg-sky-400/10' },
  '综艺':    { icon: <Tv      className="w-5 h-5" />, colorClass: 'border-sky-400 text-sky-400', bgClass: 'bg-sky-400/10' },
};

// 兜底图标：未知冷门分类用通用 Film。
const FALLBACK_CATEGORY_STYLE: CategoryStyle = {
  icon: <Film className="w-5 h-5" />,
  colorClass: 'border-gray-400 text-gray-400',
  bgClass: 'bg-gray-400/10',
};

const getCategoryStyle = (key: string, title: string): CategoryStyle => {
  // 先按后端 key 匹配（最稳定），再按 title 匹配（兼容用户在 HomepageEditor
  // 里自定义的中文标签）。两边都不命中走兜底。
  const k = (key || '').toLowerCase();
  if (DEFAULT_CATEGORY_ICONS[k]) return DEFAULT_CATEGORY_ICONS[k];
  if (DEFAULT_CATEGORY_ICONS[title]) return DEFAULT_CATEGORY_ICONS[title];
  return FALLBACK_CATEGORY_STYLE;
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

export const Home = ({ onMovieSelect, onViewMore, onRequestBindStorage }: { onMovieSelect: (m: Movie) => void; onViewMore: (id: string) => void; onRequestBindStorage?: () => void }) => {
  const [heroMovie, setHeroMovie] = useState<Movie>(() => {
     if (cachedHomepageData && cachedHomepageData.hero) return cachedHomepageData.hero;
     return FEATURED_MOVIE;
  });
  
  const [sections, setSections] = useState<any[]>(cachedHomepageData?.sections || []);

  useEffect(() => {
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

    if (!cachedHomepageData) {
      fetchHomepageData();
    }

    // 「主页设置」保存后会派发这个事件 —— 失效模块缓存并重新拉一次。
    // 不重启首页组件就能立刻看到改后的 hero / sections。
    const onConfigUpdated = () => {
      cachedHomepageData = null;
      fetchHomepageData();
    };
    window.addEventListener('homepage-config-updated', onConfigUpdated);
    // 资源库扫描结束 → 首页推荐 / 精选可能变化，缓存失效后重新拉一次。
    // 用户对 ScanProgressBar 完成不再需要手动刷新页面就能看到新增内容。
    const onScanCompleted = () => {
      cachedHomepageData = null;
      fetchHomepageData();
    };
    window.addEventListener('cyber:scan:completed', onScanCompleted);
    return () => {
      window.removeEventListener('homepage-config-updated', onConfigUpdated);
      window.removeEventListener('cyber:scan:completed', onScanCompleted);
    };
  }, []);

  // 真正的空：后端没返任何分组（无任何已挂载存储 / 已扫描资源）。
  // 用 sections.length 判定而不是 heroMovie——后端在没数据时仍然会返默认
  // FEATURED_MOVIE 当 hero 占位，那不算"有数据"。
  // 用户主动隐藏所有分组（HomepageEditor 全关）也会触发空状态——这种情况
  // 下用户能从「主页设置」打开分组，所以也指引到 RESOURCES tab + 不强制
  // 弹绑定 modal 是 OK 的。
  const isEmpty = sections.length === 0;

  if (isEmpty) {
    return (
      <div className="relative w-full min-h-[85vh] overflow-hidden flex items-center justify-center z-10 pt-20">
        {/* 背景装饰：跟 hero 同款渐变和 grid，保持赛博风一致 */}
        <div className="absolute inset-0 bg-[#0a0a12]">
          <div className="absolute inset-0 opacity-30" style={{ backgroundImage: 'radial-gradient(circle at 30% 20%, rgba(0,243,255,0.18), transparent 40%), radial-gradient(circle at 70% 80%, rgba(188,19,254,0.12), transparent 45%)' }}></div>
          <div className="absolute inset-0 bg-gradient-to-t from-[#050505] via-transparent to-transparent"></div>
        </div>

        <div className="relative z-20 max-w-2xl px-8 text-center">
          {/* 图标：硬盘 + 火花，象征"还没有数据" */}
          <div className="relative inline-flex items-center justify-center mb-8">
            <div className="absolute inset-0 bg-primary/20 blur-3xl rounded-full"></div>
            <div className="relative p-6 border-2 border-primary rounded-2xl bg-black/60 shadow-[0_0_40px_rgba(0,243,255,0.4)] backdrop-blur-sm">
              <HardDrive className="w-16 h-16 text-primary" strokeWidth={1.2} />
              <Sparkles className="absolute -top-2 -right-2 w-6 h-6 text-accent animate-pulse" />
            </div>
          </div>

          <h1 className="text-4xl md:text-5xl font-['Orbitron'] font-bold text-white mb-4 tracking-widest">
            链路<span className="text-primary">未连接</span>
          </h1>
          <p className="text-lg text-gray-300 leading-relaxed font-sans mb-2">
            还没接入任何挂载点
          </p>
          <p className="text-sm text-gray-500 leading-relaxed font-sans mb-10">
            挂载一个网盘或本地目录，CyberStream 会自动刮削元数据，
            <br />
            你的影视库立刻在这里成型。
          </p>

          <button
            onClick={() => onRequestBindStorage?.()}
            className="inline-flex items-center gap-3 px-8 py-4 border-2 border-primary bg-primary/10 hover:bg-primary text-primary hover:text-black rounded-sm font-['Orbitron'] font-bold text-base transition-all hover:scale-105 shadow-[0_0_15px_var(--color-primary)] hover:shadow-[0_0_30px_var(--color-primary)] backdrop-blur-sm"
          >
            <HardDrive className="w-5 h-5" />
            <span className="tracking-wider">立即绑定挂载点</span>
            <ChevronRight className="w-5 h-5" />
          </button>

          <p className="text-[11px] text-gray-600 mt-8 font-['Rajdhani'] tracking-widest uppercase">
            支持 阿里云盘 · 百度网盘 · 夸克 · 天翼 · 115 · WebDAV · 本地目录
          </p>
        </div>
      </div>
    );
  }

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