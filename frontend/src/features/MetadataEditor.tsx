import React, { useState, useEffect } from 'react';
import { Movie } from '../types';
import { Terminal, Save, X, RotateCcw, Search, Database, Cpu, Image as ImageIcon, ArrowLeft, Link as LinkIcon, Orbit, Layers, Lock, Unlock, RefreshCw, Zap } from 'lucide-react';
import { MovieCard } from '../components/movies/Cards';
import { TMDBMatchModal } from './TMDBMatchModal';
import { ResourceTreeManager } from './ResourceTreeManager';
import { toast } from '../utils';

interface MetadataEditorProps {
  movie: Movie;
  onClose: () => void;
  onSave: (updatedMovie: Movie) => void;
  onUpdateQuietly?: (updatedMovie: Movie) => void;
}

export const MetadataEditor: React.FC<MetadataEditorProps> = ({ movie, onClose, onSave, onUpdateQuietly }) => {
  const [editedMovie, setEditedMovie] = useState<Movie>({ ...movie });
  const [tagsInput, setTagsInput] = useState((movie.tags || []).join(', '));
  const [isScraping, setIsScraping] = useState(false);
  const [scrapeLog, setScrapeLog] = useState<string[]>([]);
  const [isMatchModalOpen, setIsMatchModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'core' | 'resources'>('core');
  const [isSaving, setIsSaving] = useState(false);

  // Prevent background scrolling
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = 'auto';
    };
  }, []);

  // Sync tagsInput when editedMovie.tags changes externally (e.g. from scraping)
  useEffect(() => {
    setTagsInput(prev => {
      const currentTags = prev.split(/[,，]/).map(t => t.trim()).filter(t => t);
      const newTags = editedMovie.tags || [];
      if (JSON.stringify(currentTags) !== JSON.stringify(newTags)) {
        return newTags.join(', ');
      }
      return prev;
    });
  }, [editedMovie.tags]);

  const handleChange = (field: keyof Movie, value: any) => {
    setEditedMovie(prev => ({ ...prev, [field]: value }));
  };

  const handleTagsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTagsInput(e.target.value);
    const tagsArray = e.target.value.split(/[,，]/).map(t => t.trim()).filter(t => t);
    handleChange('tags', tagsArray);
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const apiService = await import('../api').then(m => m.movieService);
      const lockedFieldsArray = Array.from(lockedFields);
      
      const payload = {
        ...editedMovie,
        metadata_locked_fields: lockedFieldsArray
      };

      const updatedMovie = await apiService.updateMetadata(String(movie.id), payload);
      if (updatedMovie) {
        toast.success(`[${updatedMovie.title}] 档案更新已同步至主节点`);
        onSave(updatedMovie);
      } else {
        toast.error("网络连接异常：物理层数据存档失败");
      }
    } catch (e) {
      console.error(e);
      toast.error("致命错误：无法写入数据库");
    } finally {
      setIsSaving(false);
    }
  };

  const [lockedFields, setLockedFields] = useState<Set<string>>(new Set(movie.metadata_locked_fields || []));

  const toggleLock = (field: string) => {
    setLockedFields(prev => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  // Helper inside to render locks
  const renderLabel = (field: string, labelText: string) => {
    const isLocked = lockedFields.has(field);
    return (
      <div className="flex items-center justify-between group">
        <label className="text-xs text-primary-70 group-hover:text-primary transition-colors select-none">
          {labelText}
        </label>
        <button 
          onClick={(e) => { e.preventDefault(); toggleLock(field); }}
          className={`p-1 rounded-sm border transition-all ${isLocked ? 'border-red-500/50 bg-red-500/10 text-red-500' : 'border-primary-30 bg-transparent text-primary-30 hover:text-primary hover:border-primary'}`}
          title={isLocked ? "点击解锁字段" : "点击锁定字段，防止自动刮削覆盖"}
        >
          {isLocked ? <Lock size={12} /> : <Unlock size={12} />}
        </button>
      </div>
    );
  };

  const getUnlockedFieldsArray = () => {
    // Standard fields supported by the backend for locking/unlocking
    const allFields = ['title', 'original_title', 'year', 'rating', 'overview', 'poster_url', 'backdrop_url', 'genres', 'tags', 'actors', 'director', 'country'];
    return allFields.filter(f => !lockedFields.has(f));
  };

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshLog, setRefreshLog] = useState<string[]>([]);
  
  const handleRefresh = async () => {
    setIsRefreshing(true);
    setRefreshLog(['> 启动轻量级同步...', '> 正在连线云端节点...', '> 修正异常资料块...']);
    try {
      const updatedMovie = await apiService.refreshMetadata(String(movie.id), { media_type_hint: movie.type as any });
      if (updatedMovie) {
        setRefreshLog(prev => [...prev, '> 同步完成。']);
        onSave(updatedMovie);
        // Do not close so user sees log
      } else {
        setRefreshLog(prev => [...prev, '> [错误] 同步失败']);
      }
    } catch (e) {
      setRefreshLog(prev => [...prev, '> [致命错误] 连接中断']);
    } finally {
      setTimeout(() => setIsRefreshing(false), 2000);
    }
  };

  const handleScrape = async () => {
    setIsScraping(true);
    setScrapeLog(['> 启动神经扫描...', '> 正在连接 TMDB 主机...', '> 正在解析元数据保护指令...']);
    
    try {
      const apiService = await import('../api').then(m => m.movieService);
      setScrapeLog(prev => [...prev, `> 正在应用 ${lockedFields.size} 项绝对防御机制...`]);
      
      const updatedMovie = await apiService.reScrapeMetadata(String(movie.id), {
        force_refresh: true
      });

      if (updatedMovie) {
        setEditedMovie(updatedMovie);
        if (updatedMovie.metadata_locked_fields) {
            setLockedFields(new Set(updatedMovie.metadata_locked_fields));
        }
        if (onUpdateQuietly) {
            onUpdateQuietly(updatedMovie);
        }
        toast.success(`重刮削成功：[${updatedMovie.title}] 档案库关联已重置`);
        setScrapeLog(prev => [...prev, '> 覆写完成，核心数据已同步。']);
        setTimeout(() => setIsScraping(false), 1500);
      } else {
        setScrapeLog(prev => [...prev, '> [错误] 未能从神经元网络获取有效反馈']);
        toast.warning("重刮削过程警告：节点未返回任何更新数据");
        setIsScraping(false);
      }
    } catch (error) {
      console.error(error);
      setScrapeLog(prev => [...prev, '> [致命错误] 连接协议中断']);
      toast.error("节点链路崩溃：刮削任务已中止");
      setIsScraping(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex bg-[#050505] text-primary font-mono overflow-hidden animate-in fade-in duration-300">
      {/* Scanline overlay */}
      <div 
        className="absolute inset-0 pointer-events-none bg-[linear-gradient(transparent,var(--color-primary)_50%,transparent)] bg-[length:100%_4px] z-50"
        style={{ display: 'var(--scanline-display, none)', opacity: 'var(--scanline-opacity)' }}
      ></div>
      
      {/* Left Panel: Form */}
      <div className="w-1/2 h-full border-r border-primary-30 flex flex-col relative z-10 bg-[#050505]/90 backdrop-blur-md">
        <div className="p-4 border-b border-primary-30 flex flex-col gap-4 bg-primary-10">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-2">
              <Terminal size={20} />
              <h2 className="text-xl font-bold tracking-widest text-primary-90 shadow-primary">系统控制台中心</h2>
            </div>
            <button onClick={onClose} className="hover:text-white hover:bg-red-500 p-1 transition-colors">
              <X size={24} />
            </button>
          </div>
          
          {/* Tab Navigation */}
          <div className="flex font-mono text-sm border-b border-primary-30/50 -mb-4">
            <button 
              onClick={() => setActiveTab('core')}
              className={`px-4 py-3 flex items-center gap-2 font-bold tracking-widest transition-colors border-b-2 ${activeTab === 'core' ? 'text-black bg-primary border-primary' : 'text-primary-50 hover:text-primary hover:bg-primary-20 border-transparent'}`}
            >
              <Orbit size={16} /> [ 核心档案覆写区 ]
            </button>
            <button 
              onClick={() => setActiveTab('resources')}
              className={`px-4 py-3 flex items-center gap-2 font-bold tracking-widest transition-colors border-b-2 ${activeTab === 'resources' ? 'text-black bg-primary border-primary' : 'text-primary-50 hover:text-primary hover:bg-primary-20 border-transparent'}`}
            >
              <Layers size={16} /> [ 物理层数据碎片拓扑 ]
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8 space-y-8 custom-scrollbar">
          
          {activeTab === 'core' && (
            <>
              {/* Action Buttons */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            
            {/* Refresh Button */}
            <div className="border border-primary-50 p-4 relative group cursor-pointer hover:bg-primary-10 transition-colors flex flex-col justify-center" onClick={handleRefresh}>
              <div className="absolute -top-3 left-4 bg-[#050505] px-2 text-xs text-primary-70">轻量级同步模块</div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <RefreshCw size={24} className={isRefreshing ? 'animate-spin text-white' : ''} />
                  <span className="font-bold tracking-widest">[ 更新资料 ]</span>
                </div>
                <Zap size={20} className="opacity-50 group-hover:opacity-100" />
              </div>
              {isRefreshing && (
                <div className="mt-4 text-xs text-primary space-y-1">
                  {refreshLog.map((log, i) => <div key={i} className="animate-in fade-in slide-in-from-left-2">{log}</div>)}
                </div>
              )}
            </div>

            {/* Scrape Button */}
            <div className="border border-primary-50 p-4 relative group cursor-pointer hover:bg-primary-10 transition-colors flex flex-col justify-center" onClick={handleScrape}>
              <div className="absolute -top-3 left-4 bg-[#050505] px-2 text-xs text-primary-70">深度网络刮削器</div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Database size={24} className={isScraping ? 'animate-pulse text-white' : ''} />
                  <span className="font-bold tracking-widest">[ 重新刮削 ]</span>
                </div>
                <Search size={20} className="opacity-50 group-hover:opacity-100" />
              </div>
              {isScraping && (
                <div className="mt-4 text-xs text-primary space-y-1">
                  {scrapeLog.map((log, i) => <div key={i} className="animate-in fade-in slide-in-from-left-2">{log}</div>)}
                </div>
              )}
            </div>

            {/* Match TMDB Button */}
            <div className="border border-primary-50 p-4 relative group cursor-pointer hover:bg-primary-10 transition-colors flex flex-col justify-center" onClick={() => setIsMatchModalOpen(true)}>
              <div className="absolute -top-3 left-4 bg-[#050505] px-2 text-xs text-primary-70">精准协议对接</div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <LinkIcon size={24} />
                  <span className="font-bold tracking-widest">[ 外部网络匹配 ]</span>
                </div>
                <Search size={20} className="opacity-50 group-hover:opacity-100" />
              </div>
              <div className="mt-4 text-xs text-primary-50">
                连接外部 TMDB 节点，修复身份认知错误
              </div>
            </div>
          </div>

          {/* Form Fields */}
          <div className="space-y-6">
            <div className="space-y-2 group">
              {renderLabel('title', '档案代号 (Title)')}
              <div className="relative">
                <input 
                  type="text" 
                  value={editedMovie.title} 
                  onChange={e => handleChange('title', e.target.value)}
                  className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans text-lg transition-colors peer"
                  readOnly={lockedFields.has('title')}
                />
              </div>
            </div>

            <div className="space-y-2 group">
              {renderLabel('poster_url', '视觉载体 (Poster)')}
              <div className="relative">
                <input 
                  type="text" 
                  value={editedMovie.cover_url || ''} 
                  onChange={e => handleChange('cover_url', e.target.value)}
                  className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans transition-colors peer"
                  readOnly={lockedFields.has('poster_url')}
                />
              </div>
            </div>

            <div className="space-y-2 group">
              {renderLabel('backdrop_url', '场景投影 (Backdrop)')}
              <div className="relative">
                <input 
                  type="text" 
                  value={editedMovie.backdrop_url || ''} 
                  onChange={e => handleChange('backdrop_url', e.target.value)}
                  className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans transition-colors peer"
                  readOnly={lockedFields.has('backdrop_url')}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-2 group">
                {renderLabel('year', '发行年份')}
                <input 
                  type="number" 
                  value={editedMovie.year} 
                  onChange={e => handleChange('year', parseInt(e.target.value) || 0)}
                  className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans peer"
                  readOnly={lockedFields.has('year')}
                />
              </div>
              <div className="space-y-2 group">
                {renderLabel('rating', '安全评级 (Rating)')}
                <input 
                  type="text" 
                  value={editedMovie.rating} 
                  onChange={e => handleChange('rating', e.target.value)}
                  className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans peer"
                  readOnly={lockedFields.has('rating')}
                />
              </div>
            </div>

            <div className="space-y-2 group">
              {renderLabel('tags', '标签矩阵 (逗号分隔)')}
              <input 
                type="text" 
                value={tagsInput} 
                onChange={handleTagsChange}
                className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 text-white font-sans peer"
                readOnly={lockedFields.has('tags')}
              />
              <div className="flex flex-wrap gap-2 mt-2">
                {(editedMovie.tags || []).map((tag, idx) => (
                  <span key={idx} className="text-xs px-2 py-1 bg-primary-20 border border-primary-50 text-primary rounded-sm">
                    {tag}
                  </span>
                ))}
              </div>
            </div>

            <div className="space-y-2 group">
              {renderLabel('overview', '解密日志 (简介)')}
              <div className="relative">
                <textarea 
                  value={editedMovie.desc || editedMovie.overview || ''} 
                  onChange={e => handleChange('desc', e.target.value)}
                  rows={6}
                  className="w-full bg-primary-5 border border-primary-50 focus:border-primary focus:outline-none p-3 text-white font-sans resize-none transition-colors peer custom-scrollbar"
                  readOnly={lockedFields.has('overview')}
                />
              </div>
            </div>
          </div>
          </>
          )}

          {activeTab === 'resources' && (
            <ResourceTreeManager movieId={String(movie.id)} />
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-6 border-t border-primary-30 bg-black flex gap-4">
          <button 
            onClick={onClose}
            className="px-6 border border-primary-50 hover:bg-primary-20 text-primary flex items-center justify-center gap-2 transition-colors"
            title="返回详情页"
          >
            <ArrowLeft size={18} />
          </button>
          <button 
            onClick={handleSave}
            disabled={isSaving}
            className={`flex-1 ${isSaving ? 'bg-primary-50 cursor-not-allowed' : 'bg-primary hover:bg-primary-70'} text-black font-bold py-3 flex items-center justify-center gap-2 transition-colors`}
          >
            <Save size={18} />
            {isSaving ? '[ 覆写中... ]' : '[ 覆写系统档案 ]'}
          </button>
          <button 
            onClick={() => setEditedMovie({ ...movie })}
            className="px-6 border border-primary-50 hover:bg-primary-20 text-primary flex items-center justify-center gap-2 transition-colors"
            title="回滚至出厂设置"
          >
            <RotateCcw size={18} />
          </button>
        </div>
      </div>

      {/* Right Panel: Holographic Preview */}
      <div className="w-1/2 h-full relative z-10 bg-[#0a0a12] flex flex-col items-center justify-center p-12">
        <div className="absolute top-4 right-4 text-xs text-primary-50 flex items-center gap-2">
          <span className="w-2 h-2 bg-primary rounded-full animate-pulse"></span>
          实时全息投影预览
        </div>
        
        {/* Backdrop Preview */}
        {editedMovie.backdrop_url && (
          <img 
            src={editedMovie.backdrop_url}
            alt="Backdrop Preview"
            referrerPolicy="no-referrer"
            className="absolute inset-0 w-full h-full object-cover object-center opacity-20 pointer-events-none" 
          />
        )}
        
        {/* Card Preview */}
        <div className="w-64 transform hover:scale-105 transition-transform duration-500 box-shadow-neon relative z-20">
          <MovieCard movie={editedMovie} category={{ colorClass: 'border-primary' }} onClick={() => {}} />
        </div>

        {/* Detail Preview Snippet */}
        <div className="mt-12 w-full max-w-md bg-black/60 backdrop-blur-md border border-primary-30 p-6 text-left relative z-20">
          <h3 className="text-2xl font-bold text-white mb-2 font-sans">{editedMovie.title}</h3>
          <div className="flex gap-4 text-sm text-primary mb-4">
            <span>{editedMovie.year}</span>
            <span>★ {editedMovie.rating}</span>
          </div>
          <p className="text-gray-300 text-sm line-clamp-4 font-sans leading-relaxed">
            {editedMovie.desc || editedMovie.overview || "No description available."}
          </p>
        </div>
      </div>

      {isMatchModalOpen && (
        <TMDBMatchModal 
          movieId={String(movie.id)}
          initialQuery={editedMovie.title}
          initialYear={editedMovie.year}
          unlockedFields={getUnlockedFieldsArray()}
          onClose={() => setIsMatchModalOpen(false)}
          onMatch={(updatedMovie) => {
            setEditedMovie(updatedMovie);
            if (onUpdateQuietly) {
              onUpdateQuietly(updatedMovie);
            }
            if (updatedMovie.metadata_locked_fields) {
              setLockedFields(new Set(updatedMovie.metadata_locked_fields));
            }
            setIsMatchModalOpen(false);
          }}
        />
      )}
    </div>
  );
};
