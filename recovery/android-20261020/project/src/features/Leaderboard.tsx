import React, { useState, useEffect } from 'react';
import { BarChart3, Loader2 } from 'lucide-react';
import { TopCard, RankRow, getRankStyle } from '../components/movies/Cards';
import { Movie } from '../types';
import { movieService } from '../api';

export const Leaderboard = ({ onMovieSelect }: { onMovieSelect: (m: Movie) => void }) => { 
  const [activeTime, setActiveTime] = useState('WEEKLY'); 
  const [activeType, setActiveType] = useState('HOT'); 
  const [rankList, setRankList] = useState<Movie[]>([]); 
  const [loading, setLoading] = useState(true); 
  
  useEffect(() => { 
    const fetchTop = async () => { 
      setLoading(true); 
      try { 
        // OpenAPI does not have specific top endpoints yet, using getTop which now falls back to generic list + sort
        const data = await movieService.getTop(activeType, 15);
        if (Array.isArray(data)) { setRankList(data); } 
      } catch (e) { console.error(e); } finally { setLoading(false); } 
    }; 
    fetchTop(); 
    window.scrollTo(0, 0); 
  }, [activeType, activeTime]); 
  
  const topThree = rankList.slice(0, 3); 
  const restList = rankList.slice(3); 
  
  return (
    <div className="min-h-screen w-full pt-24 px-4 md:px-12 pb-12"> 
      {/* Container to prevent infinite stretching on ultra-wide screens */}
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-8 border-b border-white/10 pb-6"> 
          <div> 
            <div className="flex items-center gap-3 mb-2"><BarChart3 className="text-primary" size={24} /><h2 className="text-sm font-['Orbitron'] text-primary tracking-[0.2em]">CYBER_RANKINGS</h2></div> 
            <h1 className="text-4xl font-['Noto_Sans_SC'] font-bold text-white glitch-text" data-text="全网热度排行">全网热度排行</h1> 
          </div> 
          <div className="flex flex-col gap-4"> 
            <div className="flex bg-black/40 border border-white/10 p-1 rounded-sm">{['HOT', 'RATED', 'NEW'].map(type => (<button key={type} onClick={() => setActiveType(type)} className={`px-6 py-1.5 text-xs font-['Orbitron'] font-bold transition-all ${activeType === type ? 'bg-primary text-black shadow-[0_0_10px_var(--color-primary)]' : 'text-gray-400 hover:text-white'}`}>{type === 'HOT' ? '热度榜' : type === 'RATED' ? '好评榜' : '新片榜'}</button>))}</div> 
            <div className="flex gap-4 text-xs font-['Rajdhani'] justify-end">{['WEEKLY', 'MONTHLY', 'ALL_TIME'].map(time => (<button key={time} onClick={() => setActiveTime(time)} className={`pb-1 border-b-2 transition-colors ${activeTime === time ? 'text-white border-secondary' : 'text-gray-500 border-transparent hover:text-gray-300'}`}>{time}</button>))}</div> 
          </div> 
        </div> 

        {loading ? (
          <div className="h-96 flex items-center justify-center text-primary"><Loader2 className="animate-spin" size={48} /></div>
        ) : rankList.length === 0 ? (
          <div className="h-64 flex items-center justify-center text-gray-500">暂无排名数据</div>
        ) : (
          <> 
            {/* Top 3 Podium Layout - Centered Flex instead of Grid for better proportion control */}
            <div className="flex flex-col md:flex-row justify-center items-end gap-4 md:gap-8 mb-10 min-h-[380px]"> 
              
              {/* Rank 2 (Left) */}
              {topThree[1] && (
                <div className="order-2 md:order-1 w-full md:w-1/3 max-w-[240px] relative z-0">
                  <TopCard movie={topThree[1]} rank={2} style={getRankStyle(2)} onClick={onMovieSelect} />
                </div>
              )} 

              {/* Rank 1 (Center - Larger & Elevated) */}
              {topThree[0] && (
                <div className="order-1 md:order-2 w-full md:w-1/3 max-w-[280px] z-10 md:-mb-8 transform md:scale-110 origin-bottom transition-transform">
                  <TopCard movie={topThree[0]} rank={1} style={getRankStyle(1)} onClick={onMovieSelect} />
                </div>
              )} 

              {/* Rank 3 (Right) */}
              {topThree[2] && (
                <div className="order-3 md:order-3 w-full md:w-1/3 max-w-[240px] relative z-0">
                  <TopCard movie={topThree[2]} rank={3} style={getRankStyle(3)} onClick={onMovieSelect} />
                </div>
              )} 
            </div> 

            {/* List Section */}
            <div className="bg-[#0a0a12]/80 border border-white/10 backdrop-blur-sm rounded-sm overflow-hidden shadow-2xl"> 
              <div className="grid grid-cols-12 gap-4 p-4 text-xs font-['Orbitron'] text-gray-500 border-b border-white/5 uppercase tracking-wider bg-black/40"> 
                <div className="col-span-1 text-center">Rank</div> 
                <div className="col-span-1"></div> 
                <div className="col-span-5 md:col-span-6">Title</div> 
                <div className="col-span-2 text-center">Rating</div> 
                <div className="col-span-2 text-center">Trend</div> 
                <div className="col-span-1 text-center hidden md:block">Views</div> 
              </div> 
              <div className="divide-y divide-white/5">
                {restList.map((movie, index) => (
                  <RankRow key={movie.id} movie={movie} rank={index + 4} onClick={onMovieSelect} />
                ))} 
              </div>
            </div> 
          </>
        )} 
      </div>
    </div>
  ); 
};