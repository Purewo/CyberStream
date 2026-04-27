import React, { useState } from 'react';
import { Search, Loader2, Check, X, Database } from 'lucide-react';
import { movieService } from '../api';
import { toast } from '../utils';

interface TMDBMatchModalProps {
  movieId: string;
  initialQuery: string;
  initialYear?: number;
  unlockedFields?: string[];
  onClose: () => void;
  onMatch: (updatedMovie: any) => void;
}

export const TMDBMatchModal: React.FC<TMDBMatchModalProps> = ({ movieId, initialQuery, initialYear, unlockedFields = [], onClose, onMatch }) => {
  const [query, setQuery] = useState(initialQuery);
  const [year, setYear] = useState<number | ''>(initialYear || '');
  const [candidates, setCandidates] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isMatching, setIsMatching] = useState(false);
  const [selectedTmdbId, setSelectedTmdbId] = useState<string | null>(null);

  const handleSearch = async () => {
    setIsSearching(true);
    try {
      const results = await movieService.searchMetadataCandidates(movieId, query, year === '' ? undefined : Number(year));
      if (results.length === 0) {
        toast.info('未在外部网络找到匹配节点');
      } else {
        toast.success(`提取到 ${results.length} 个候选节点`);
      }
      setCandidates(results);
    } catch (e) {
      console.error(e);
      toast.error('检索神经元网络失败');
    } finally {
      setIsSearching(false);
    }
  };

  const handleMatch = async (tmdbId: string, mediaType: 'movie' | 'tv') => {
    setSelectedTmdbId(tmdbId);
    setIsMatching(true);
    try {
      const updatedMovie = await movieService.matchMetadata(movieId, tmdbId, unlockedFields, mediaType);
      if (updatedMovie) {
        toast.success(`成功绑定！系统档案已被 [${updatedMovie.title}] 覆盖`);
        onMatch(updatedMovie);
      } else {
        toast.error('档案覆写失败，请检查相关实体设置或网络状态');
      }
    } catch (e) {
      console.error(e);
      toast.error('绑定时发生致命错误');
    } finally {
      setIsMatching(false);
      setSelectedTmdbId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#0a0a12] border border-primary-50 w-full max-w-3xl max-h-[85vh] flex flex-col font-mono text-primary box-shadow-neon">
        {/* Header */}
        <div className="p-4 border-b border-primary-30 flex justify-between items-center bg-primary-10">
          <div className="flex items-center gap-2">
            <Database size={20} />
            <h3 className="font-bold tracking-widest text-lg">外部神经源精准匹配 (TMDB)</h3>
          </div>
          <button onClick={onClose} className="hover:text-white hover:bg-red-500 p-1 transition-colors">
            <X size={24} />
          </button>
        </div>

        {/* Search Bar */}
        <div className="p-6 border-b border-primary-30 bg-[#050505] space-y-4">
          <div className="flex gap-4">
            <div className="flex-1 space-y-1">
              <label className="text-xs text-primary-70">实体代号 (标题)</label>
              <input 
                type="text" 
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans transition-colors"
                placeholder="在此输入需要检索的标题..."
              />
            </div>
            <div className="w-32 space-y-1">
              <label className="text-xs text-primary-70">时间锚点 (年份)</label>
              <input 
                type="number" 
                value={year}
                onChange={e => setYear(e.target.value === '' ? '' : Number(e.target.value))}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans transition-colors"
                placeholder="e.g. 2024"
              />
            </div>
            <div className="flex items-end">
              <button 
                onClick={handleSearch}
                disabled={isSearching}
                className="bg-primary text-black px-6 py-2 pb-3 font-bold flex items-center justify-center gap-2 hover:bg-primary-70 transition-colors disabled:bg-primary-30 disabled:cursor-not-allowed h-[42px]"
              >
                {isSearching ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
                [ 搜寻 ]
              </button>
            </div>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar bg-[#050505]/50">
          {isSearching ? (
            <div className="flex flex-col items-center justify-center h-48 space-y-4 text-primary-70">
              <Loader2 size={32} className="animate-spin text-primary" />
              <p className="animate-pulse tracking-widest text-sm">正在深度挖掘外部网络节点...</p>
            </div>
          ) : candidates.length > 0 ? (
            <div className="grid grid-cols-1 gap-4 text-left">
              {candidates.map((cand, idx) => (
                <div key={idx} className="border border-primary-30 bg-black/60 p-4 hover:border-primary-70 hover:bg-primary-10 transition-colors flex gap-4 group">
                  <div className="w-16 h-24 bg-primary-20 flex-shrink-0 flex items-center justify-center overflow-hidden border border-primary-30">
                    {(cand.poster_path || cand.poster_url || cand.poster) ? (
                      <img 
                        src={
                          (cand.poster_url || cand.poster) 
                            ? (cand.poster_url || cand.poster)
                            : `https://image.tmdb.org/t/p/w200${cand.poster_path}`
                        } 
                        alt={cand.title || cand.name} 
                        className="w-full h-full object-cover" 
                        referrerPolicy="no-referrer"
                        onError={(e) => {
                          (e.target as HTMLImageElement).src = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiPjxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbGw9IiMzMyMiLz48dGV4dCB4PSI1MCUiIHk9IjUwJSIgZmlsbD0iIzY2NiIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTQiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5ObyBJbWFnZTwvdGV4dD48L3N2Zz4=';
                        }}
                      />
                    ) : (
                      <span className="text-xs text-primary-50">无图像</span>
                    )}
                  </div>
                  <div className="flex-1 flex flex-col justify-between overflow-hidden">
                    <div>
                      <div className="flex justify-between items-start">
                        <h4 className="font-bold text-white text-lg font-sans truncate">{cand.title || cand.name}</h4>
                        <span className="text-xs text-primary-50 px-2 py-0.5 border border-primary-50 bg-primary-10 whitespace-nowrap">TMDB ID: {cand.tmdb_id || cand.id}</span>
                      </div>
                      <div className="text-sm text-primary-70 font-sans mt-1">
                        年份: <span className="text-primary">{cand.year ? cand.year : (cand.release_date ? cand.release_date.substring(0,4) : (cand.first_air_date ? cand.first_air_date.substring(0,4) : '未知'))}</span> | 
                        类型: <span className="text-primary">{cand.media_type === 'tv' ? '剧集' : '电影'}</span> | 
                        原名: <span className="text-primary-50 truncate">{cand.original_title || cand.original_name || '-'}</span>
                      </div>
                      <p className="text-xs text-primary-50 mt-2 line-clamp-2 font-sans leading-relaxed">{cand.overview}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-center ml-4">
                    <button 
                      onClick={() => handleMatch(String(cand.tmdb_id || cand.id), cand.media_type)}
                      disabled={isMatching && selectedTmdbId === String(cand.tmdb_id || cand.id)}
                      className="border border-primary text-primary px-4 py-2 hover:bg-primary hover:text-black font-bold flex items-center gap-2 transition-colors disabled:opacity-50 min-w-[120px] justify-center"
                    >
                      {isMatching && selectedTmdbId === String(cand.tmdb_id || cand.id) ? (
                         <Loader2 size={16} className="animate-spin" />
                      ) : (
                         <Check size={16} />
                      )}
                      {isMatching && selectedTmdbId === String(cand.tmdb_id || cand.id) ? '绑定中' : '匹配'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-48 space-y-4 text-primary-50">
              <Database size={32} className="opacity-50" />
              <p className="tracking-widest text-sm">数据库中未找到符合条件的实体或尚未检索</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
