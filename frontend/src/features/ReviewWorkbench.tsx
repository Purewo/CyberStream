import React, { useState, useEffect } from 'react';
import { ShieldAlert, AlertTriangle, CheckCircle, Database, Server, Loader2, ArrowRight, BarChart3, Fingerprint, Search, Filter, RefreshCw, Layers, RotateCw } from 'lucide-react';
import { movieService } from '../api';
import { Movie, MetadataOverview } from '../types';
import { MovieCard } from '../components/movies/Cards';
import { MetadataEditor } from './MetadataEditor';

export const ReviewWorkbench = () => {
  const [activeTab, setActiveTab] = useState<'movies' | 'zombies'>('movies');
  const [workItems, setWorkItems] = useState<any[]>([]);
  const [zombies, setZombies] = useState<any[]>([]);
  const [overview, setOverview] = useState<MetadataOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [selectedMovie, setSelectedMovie] = useState<Movie | null>(null);
  
  // Filters
  const [priority, setPriority] = useState<string>('all');
  const [needsAttention, setNeedsAttention] = useState<boolean>(true);

  const fetchStats = async () => {
    setStatsLoading(true);
    try {
      const data = await movieService.getMetadataOverview();
      if (data) setOverview(data);
    } catch (e) {
      console.error("Failed to load overview data", e);
    } finally {
      setStatsLoading(false);
    }
  };

  const fetchMovies = async (pageNum: number) => {
    setLoading(true);
    try {
      const filters: any = {};
      if (priority !== 'all') filters.metadata_review_priority = priority;
      if (needsAttention) filters.needs_attention = true;

      const data = await movieService.getAll(15, pageNum, filters);
      if (data) {
        setWorkItems(data.items.map(movie => ({ movie })));
        if (data.meta) setTotalPages(data.meta.total_pages);
      }
    } catch (e) {
      console.error("Failed to load work items", e);
    } finally {
      setLoading(false);
    }
  };

  const fetchZombies = async (pageNum: number) => {
    import('../api').then(({ systemService }) => {
      setLoading(true);
      systemService.getReviewResources(pageNum, 15).then((data) => {
        if (data) {
          setZombies(data.items);
          if (data.pagination) setTotalPages(data.pagination.total_pages);
        }
        setLoading(false);
      }).catch(e => {
        console.error("Failed to load zombie resources", e);
        setLoading(false);
      });
    });
  };

  useEffect(() => {
    fetchStats();
  }, []);

  useEffect(() => {
    setPage(1);
  }, [activeTab, priority, needsAttention]);

  useEffect(() => {
    if (activeTab === 'movies') {
       fetchMovies(page);
    } else {
       fetchZombies(page);
    }
  }, [page, activeTab, priority, needsAttention]);

  const [isBatchScraping, setIsBatchScraping] = useState(false);
  const handleBatchScrape = async () => {
      const ids = workItems.map(w => String(w.movie?.id)).filter(i => i && i !== 'undefined');
      if (ids.length === 0) return;
      setIsBatchScraping(true);
      try {
          await movieService.batchReScrapeMetadata(ids, { force_refresh: true });
          fetchStats();
          fetchMovies(page);
      } catch (e) {
          console.error("Batch retry failed", e);
      } finally {
          setIsBatchScraping(false);
      }
  };

  const handleMovieUpdate = (updated: Movie) => {
    setWorkItems(prev => prev.map(item => item.movie?.id === updated.id ? { ...item, movie: updated } : item));
    setSelectedMovie(null);
    fetchStats(); // Update stats if item was fixed
  };

  return (
    <div className="min-h-screen w-full pt-20 px-4 md:px-12 pb-12 bg-[#050505] font-mono">
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="p-2 border border-primary text-primary shadow-primary bg-primary-10">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-white tracking-widest flex items-center gap-4">
            METADATA <span className="text-primary">GOVERNANCE</span>
          </h1>
          <div className="text-[10px] text-primary-50 mt-1 uppercase tracking-[0.3em]">CyberStream 元数据治理与审核控制中心 v1.16</div>
        </div>
        <div className="flex-grow h-[1px] bg-gradient-to-r from-primary/50 to-transparent"></div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <div className="border border-primary-30 bg-primary-5 p-4 relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-30 transition-opacity">
                <BarChart3 size={40} />
            </div>
            <div className="text-xs text-primary-50 mb-1 uppercase tracking-wider">总收录影片</div>
            <div className="text-3xl font-bold text-white">{statsLoading ? '---' : overview?.total_movies || 0}</div>
            <div className="mt-2 h-1 bg-primary-20 w-full overflow-hidden">
                <div className="h-full bg-primary animate-pulse" style={{ width: '100%' }}></div>
            </div>
        </div>

        <div className="border border-red-500/30 bg-red-500/5 p-4 relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-30 transition-opacity">
                <AlertTriangle size={40} className="text-red-500" />
            </div>
            <div className="text-xs text-red-400 mb-1 uppercase tracking-wider">待优化实体</div>
            <div className="text-3xl font-bold text-white">{statsLoading ? '---' : overview?.needs_attention_count || 0}</div>
            <div className="mt-2 h-1 bg-red-500/20 w-full overflow-hidden">
                <div className="h-full bg-red-500" style={{ width: overview?.total_movies ? `${(overview.needs_attention_count / overview.total_movies * 100)}%` : '0%' }}></div>
            </div>
        </div>

        <div className="border border-primary-30 bg-primary-5 p-4 relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-30 transition-opacity">
                <Layers size={40} />
            </div>
            <div className="text-xs text-primary-50 mb-1 uppercase tracking-wider">物理资源总数</div>
            <div className="text-3xl font-bold text-white">{statsLoading ? '---' : overview?.total_resources || 0}</div>
        </div>

        <div className="border border-primary-30 bg-primary-5 p-4 relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-30 transition-opacity">
                <Fingerprint size={40} />
            </div>
            <div className="text-xs text-primary-50 mb-1 uppercase tracking-wider">元数据完整率</div>
            <div className="text-3xl font-bold text-primary">
                {statsLoading || !overview?.total_movies ? '---' : `${((1 - overview.needs_attention_count / overview.total_movies) * 100).toFixed(1)}%`}
            </div>
        </div>
      </div>

      <div className="flex gap-4 mb-4">
        <button 
          onClick={() => setActiveTab('movies')}
          className={`flex-1 py-3 text-sm font-bold tracking-widest uppercase transition-colors ${activeTab === 'movies' ? 'bg-primary text-black border-b-2 border-white' : 'bg-primary-5 text-primary border border-primary-30'}`}
        >
          异常影视实体 (Movies)
        </button>
        <button 
          onClick={() => setActiveTab('zombies')}
          className={`flex-1 py-3 text-sm font-bold tracking-widest uppercase transition-colors ${activeTab === 'zombies' ? 'bg-red-500 text-black border-b-2 border-white' : 'bg-red-500/10 text-red-500 border border-red-500/30'}`}
        >
          僵尸资源池 (Zombie Resources)
        </button>
      </div>

      <div className="flex justify-between items-center bg-[#0a0a12]/80 border border-primary-30/30 p-4 mb-6 backdrop-blur-sm">
        {activeTab === 'movies' && (
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
                <Filter size={16} className="text-primary-70" />
                <span className="text-xs text-primary-50 uppercase tracking-widest">审核优先级:</span>
                <select 
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    className="bg-black border border-primary-30 text-xs px-2 py-1 focus:border-primary outline-none text-primary"
                >
                    <option value="all">全部级别</option>
                    <option value="high">HIGH PRIORITY (紧急)</option>
                    <option value="medium">MEDIUM (普通)</option>
                    <option value="low">LOW (次要)</option>
                </select>
            </div>

            <div className="flex items-center gap-2">
                <input 
                    type="checkbox" 
                    id="needsAttention"
                    checked={needsAttention}
                    onChange={(e) => setNeedsAttention(e.target.checked)}
                    className="accent-primary"
                />
                <label htmlFor="needsAttention" className="text-xs text-primary-50 uppercase tracking-widest cursor-pointer hover:text-primary">仅显示待复核</label>
            </div>
          </div>
        )}

        <button 
            onClick={() => { fetchStats(); fetchMovies(1); }}
            className="flex items-center gap-2 text-xs text-primary hover:text-white transition-colors"
        >
            <RefreshCw size={14} className={statsLoading ? 'animate-spin' : ''} />
            同步最新数据状态
        </button>
      </div>

      {activeTab === 'movies' && workItems.length > 0 && (
          <div className="flex justify-end mb-4">
              <button 
                  onClick={handleBatchScrape} 
                  disabled={isBatchScraping}
                  className="flex items-center gap-2 px-4 py-2 bg-primary/20 hover:bg-primary/40 text-primary border border-primary/50 text-xs font-bold tracking-widest uppercase transition-colors rounded-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                  {isBatchScraping ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
                  批量强制重刮削本页
              </button>
          </div>
      )}

      {/* Main Content */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-32 space-y-4">
          <Loader2 size={48} className="animate-spin text-primary" />
          <div className="text-sm font-bold tracking-[0.5em] text-primary animate-pulse">正在深度同步数据库节点...</div>
        </div>
      ) : activeTab === 'movies' ? (
        workItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 border border-primary-30 border-dashed bg-primary-5 rounded-lg space-y-6">
            <CheckCircle size={64} className="text-primary opacity-20" />
            <div className="text-center">
              <p className="text-xl font-bold text-white mb-2 tracking-widest uppercase">系统完整度检测通过</p>
              <p className="text-primary-50 text-sm">当前采样范围内未检测到异常元数据实体。</p>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4 md:gap-6 justify-center">
              {workItems.map(item => {
                const movie = item.movie;
                if (!movie) return null;
                return (
                <div 
                  key={movie.id} 
                  className="relative group transition-all duration-300 transform hover:-translate-y-2 flex flex-col"
                >
                  <div onClick={() => setSelectedMovie(movie)}>
                    <MovieCard movie={movie} category={{ colorClass: 'border-primary' }} onClick={() => setSelectedMovie(movie)} />
                  </div>
                  {movie.isUnscraped && (
                      <div className="absolute top-2 right-2 bg-red-500 text-black text-[10px] font-bold px-1 py-0.5 animate-pulse z-20">
                          PENDING
                      </div>
                  )}
                  {movie.metadata_state?.primary_issue_code && (
                      <div className="mt-2 text-xs text-red-400 bg-red-500/10 border border-red-500/30 px-2 py-1 truncate" title={movie.metadata_state.recommended_action || movie.metadata_state.primary_issue_code}>
                        <AlertTriangle size={10} className="inline mr-1" />
                        {movie.metadata_state.primary_issue_code}
                      </div>
                  )}
                </div>
                );
              })}
            </div>

            {/* Pagination for Movies */}
            {totalPages > 1 && (
              <div className="flex justify-center items-center gap-6 mt-12 bg-primary-5 p-4 border border-primary-30 inline-flex mx-auto w-auto">
                <button 
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-4 py-2 border border-primary-50 text-xs hover:bg-primary hover:text-black disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-primary transition-all font-bold tracking-widest"
                 >
                   [ PREV ]
                 </button>
                 <div className="px-4 text-white font-bold text-sm tracking-[0.2em]">
                   PAGE {page} / {totalPages}
                 </div>
                 <button 
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-4 py-2 border border-primary-50 text-xs hover:bg-primary hover:text-black disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-primary transition-all font-bold tracking-widest"
                 >
                   [ NEXT ]
                 </button>
              </div>
            )}
          </div>
        )
      ) : (
        /* Zombie Resources View */
        zombies.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 border border-red-500/20 border-dashed bg-red-500/5 rounded-lg space-y-6">
            <CheckCircle size={64} className="text-red-500 opacity-20" />
            <div className="text-center">
              <p className="text-xl font-bold text-white mb-2 tracking-widest uppercase">清理完成</p>
              <p className="text-red-500/50 text-sm">资源池中没有标记为需要审核的散落资源。</p>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
             <div className="bg-black/40 border border-white/10 overflow-hidden">
                <table className="w-full text-left text-xs">
                  <thead className="bg-white/5 text-gray-500 uppercase tracking-widest border-b border-white/10">
                    <tr>
                      <th className="px-6 py-4 font-bold">Resource ID</th>
                      <th className="px-6 py-4 font-bold">Filename / Path</th>
                      <th className="px-6 py-4 font-bold">Source</th>
                      <th className="px-6 py-4 font-bold">Quality</th>
                      <th className="px-6 py-4 font-bold text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {zombies.map((res: any) => (
                      <tr key={res.resource_id} className="hover:bg-white/5 transition-colors group">
                        <td className="px-6 py-4 font-mono text-primary-50">#{res.resource_id}</td>
                        <td className="px-6 py-4 max-w-md">
                          <div className="text-white font-bold truncate mb-1">{res.filename}</div>
                          <div className="text-gray-500 truncate text-[10px]">{res.relative_path}</div>
                        </td>
                        <td className="px-6 py-4">
                          <span className="px-2 py-1 bg-white/5 border border-white/10 rounded text-gray-400">{res.source_name}</span>
                        </td>
                        <td className="px-6 py-4">
                           {res.quality_label && (
                             <span className="text-yellow-500 font-bold">{res.quality_label}</span>
                           )}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <button className="text-primary hover:underline font-bold uppercase tracking-widest">
                            [ Re-Match ]
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
             </div>

             {/* Pagination for Zombies */}
             {totalPages > 1 && (
              <div className="flex justify-center items-center gap-6 mt-8">
                <button 
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-4 py-2 border border-white/20 text-xs hover:bg-white/10 disabled:opacity-30 transition-all font-bold"
                 >
                   PREV
                 </button>
                 <div className="text-white font-bold text-xs tracking-widest">
                    {page} / {totalPages}
                 </div>
                 <button 
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-4 py-2 border border-white/20 text-xs hover:bg-white/10 disabled:opacity-30 transition-all font-bold"
                 >
                   NEXT
                 </button>
              </div>
            )}
          </div>
        )
      )}

      {/* Editor Overlay */}
      {selectedMovie && (
        <MetadataEditor 
          movie={selectedMovie} 
          onClose={() => setSelectedMovie(null)} 
          onUpdateQuietly={(updatedMovie) => {
            setWorkItems(prev => prev.map(m => m.movie?.id === updatedMovie.id ? { ...m, movie: updatedMovie } : m));
            setSelectedMovie(updatedMovie); 
          }}
          onSave={handleMovieUpdate}
        />
      )}
    </div>
  );
};
