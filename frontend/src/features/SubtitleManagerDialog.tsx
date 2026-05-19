import React, { useState, useEffect } from 'react';
import { X, Search, Check, Trash2, Download, Upload, AlertCircle, Loader2, Globe, FileText, Star } from 'lucide-react';
import { movieService } from '../api';
import { ResourceSubtitleItem } from '../types';
import { toast } from '../utils';

interface SubtitleManagerDialogProps {
  resourceId: string;
  initialSubtitles: ResourceSubtitleItem[];
  defaultSubtitleId?: string;
  movieTitle: string;
  season?: number;
  episode?: number;
  onClose: () => void;
  onSubtitlesChange: (items: ResourceSubtitleItem[], defaultId?: string) => void;
}

export const SubtitleManagerDialog: React.FC<SubtitleManagerDialogProps> = ({ 
  resourceId, 
  initialSubtitles, 
  defaultSubtitleId,
  movieTitle, 
  season, 
  episode,
  onClose,
  onSubtitlesChange
}) => {
  const [subtitles, setSubtitles] = useState<ResourceSubtitleItem[]>(initialSubtitles || []);
  const [activeDefaultId, setActiveDefaultId] = useState<string | undefined>(defaultSubtitleId);
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [isProcessing, setIsProcessing] = useState<string | null>(null);

  useEffect(() => {
    // Generate a good default keyword
    let ks = movieTitle;
    if (season && episode) {
        // Just the title since the backend sorts by season/episode automatically according to OpenAPI comments
        ks = movieTitle;
    }
    setSearchKeyword(ks);
  }, [movieTitle, season, episode]);

  const handleSearch = async () => {
    if (!searchKeyword.trim()) return;
    setIsSearching(true);
    setSearchResults([]);
    try {
      const res = await movieService.searchOnlineSubtitles(resourceId, searchKeyword);
      setSearchResults(res?.items || []);
    } catch (e: any) {
      toast.error('搜索字幕失败: ' + (e.message || String(e)));
    } finally {
      setIsSearching(false);
    }
  };

  const handleBind = async (candidateId: string) => {
    setIsProcessing(candidateId);
    try {
      const res = await movieService.bindOnlineSubtitle(resourceId, candidateId);
      // Backend returns updated playback.subtitles
      if (res && res.items) {
          setSubtitles(res.items);
          if (res.default_subtitle_id) setActiveDefaultId(res.default_subtitle_id);
          onSubtitlesChange(res.items, res.default_subtitle_id);
      } else {
          toast.success('成功绑定字幕，请刷新页面应用');
          onClose();
      }
    } catch (e: any) {
      toast.error('绑定字幕失败: ' + (e.message || String(e)));
    } finally {
      setIsProcessing(null);
    }
  };

  const handleDelete = async (subtitleId: string) => {
    try {
      // The openapi delete does not return updated object but just 200
      await movieService.deleteSubtitle(resourceId, subtitleId);
      const updated = subtitles.filter(s => s.id !== subtitleId);
      setSubtitles(updated);
      onSubtitlesChange(updated, activeDefaultId === subtitleId ? undefined : activeDefaultId);
    } catch (e: any) {
      toast.error('移除字幕失败: ' + (e.message || String(e)));
    }
  };

  const handleSetDefault = async (subtitleId: string) => {
    try {
      await movieService.setDefaultSubtitle(resourceId, subtitleId);
      setActiveDefaultId(subtitleId);
      onSubtitlesChange(subtitles, subtitleId);
    } catch (e: any) {
      toast.error('设置默认字幕失败: ' + (e.message || String(e)));
    }
  };

  const currentBoundSubtitles = subtitles.filter(s => s.source === 'online_bound' || s.source === 'manual_upload');
  const localSubtitles = subtitles.filter(s => s.source === 'sidecar');

  return (
    <div 
      className="fixed inset-0 bg-black/90 backdrop-blur-md z-[200] flex items-center justify-center p-4 animate-in fade-in"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <div 
        className="bg-[#050505] border border-primary/30 w-full max-w-2xl rounded-sm shadow-[0_0_30px_rgba(0,243,255,0.15)] flex flex-col h-[80vh] relative overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Cyberpunk accent lines */}
        <div className="absolute top-0 left-0 w-full h-[2px] bg-gradient-to-r from-transparent via-primary to-transparent opacity-50"></div>
        <div className="absolute bottom-0 left-0 w-full h-[1px] bg-primary/20"></div>

        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/20 shrink-0">
          <div className="flex items-center gap-3">
            <Globe className="text-[#00f3ff] w-5 h-5" />
            <h2 className="text-xl font-bold tracking-widest text-white">字幕管理系统</h2>
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-white transition-colors border border-transparent hover:border-white/20">
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-10 custom-scrollbar">
          
          {/* Current Subtitles */}
          <div className="space-y-4 relative">
            <h3 className="text-base font-bold text-[#00f3ff] tracking-widest flex items-center gap-2 mb-6">
                <span className="w-2 h-2 bg-[#00f3ff]"></span> 现用字幕
            </h3>
            
            {subtitles.length === 0 ? (
                <div className="text-center py-8 bg-black border border-white/20 text-gray-500 text-sm tracking-wider">
                    未绑定或未发现本地字幕
                </div>
            ) : (
                <div className="space-y-3">
                    {subtitles.map(sub => {
                        const isOnline = sub.source === 'online_bound' || sub.source === 'manual_upload';
                        const isDefault = activeDefaultId === sub.id || sub.is_default;
                        
                        return (
                            <div key={sub.id} className="flex flex-col sm:flex-row sm:items-center justify-between bg-black border border-white/20 p-4 transition-colors relative">
                                <div className="flex items-center gap-4 overflow-hidden mb-3 sm:mb-0">
                                    <FileText size={18} className={isOnline ? 'text-[#00f3ff]' : 'text-gray-500'} />
                                    <div className="flex flex-col truncate w-full sm:w-[75%]">
                                        <span className="text-[14px] text-white truncate font-bold tracking-wider mb-2" title={(sub.label && sub.label.startsWith('Unknown')) ? (sub.filename || sub.label || sub.title) : (sub.label || sub.filename || sub.title)}>
                                            {(sub.label && sub.label.startsWith('Unknown')) ? (sub.filename || sub.label || sub.title) : (sub.label || sub.filename || sub.title)}
                                        </span>
                                        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs font-bold text-gray-500 uppercase tracking-widest font-['Orbitron']">
                                            <div className="border border-white/10 px-3 py-1 bg-white/5 flex items-center justify-center min-w-[60px]">
                                                <span className={
                                                    sub.source === 'online_bound' && sub.online?.provider_id === 'subhd' ? 'text-blue-400' :
                                                    sub.source === 'online_bound' && sub.online?.provider_id === 'srtku' ? 'text-green-400' :
                                                    'text-gray-400'
                                                }>
                                                    {sub.source === 'online_bound' ? (sub.online?.provider_name || sub.online?.provider_id || sub.source) : sub.source}
                                                </span>
                                            </div>
                                            {sub.format && (
                                                <span className="flex items-center gap-2">
                                                    <div className="w-4 h-2.5 border border-white/50 rounded-sm"></div>
                                                    <span className="text-gray-500">{sub.format}</span>
                                                </span>
                                            )}
                                            {sub.web_player && sub.web_player.supported === false && (
                                                <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-orange-500" title="不兼容网页播放器">
                                                    <span>⚠️ 不兼容网页播放器</span>
                                                </span>
                                            )}
                                            {sub.language && (
                                                <span className="flex items-center gap-2 border-l border-white/10 pl-4">
                                                    <span className="text-gray-400">{typeof sub.language === 'string' ? sub.language : (sub.language?.label || sub.language?.name || sub.language?.code || 'UNKNOWN')}</span>
                                                </span>
                                            )}
                                            {sub.online?.quality && (
                                                <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-[#00f3ff]/80">
                                                    <Star size={12} className="fill-[#00f3ff]/30" /> {sub.online.quality}
                                                </span>
                                            )}
                                            {sub.online?.uploader && (
                                                <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-400">
                                                    👤 {sub.online.uploader}
                                                </span>
                                            )}
                                            {sub.online?.download_number && (
                                                <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-500">
                                                    <Download size={12} /> {sub.online.download_number}
                                                </span>
                                            )}
                                            {sub.online?.file_size && (
                                                <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-500">
                                                    {sub.online.file_size}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div className="flex items-center gap-4 shrink-0 sm:self-auto uppercase">
                                    {isDefault ? (
                                        <span className="text-xs bg-transparent text-[#00f3ff] px-4 py-2 border border-[#00f3ff] flex items-center gap-2 font-bold tracking-widest">
                                            <Check size={14} /> 默认项
                                        </span>
                                    ) : (
                                        <button 
                                            onClick={() => handleSetDefault(sub.id)}
                                            className="text-xs text-gray-500 hover:text-[#00f3ff] px-4 py-2 border border-transparent hover:border-[#00f3ff] transition-all font-bold tracking-widest"
                                        >
                                            设为默认
                                        </button>
                                    )}
                                    {isOnline && (
                                        <button 
                                            onClick={() => handleDelete(sub.id)}
                                            className="p-1.5 text-red-500/70 hover:text-red-500 transition-colors"
                                            title="移除"
                                        >
                                            <Trash2 size={18} />
                                        </button>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
          </div>

          <div className="w-full h-px bg-white/20 my-10"></div>
          
          {/* Online Search */}
          <div className="space-y-4 relative">
            <div className="absolute -left-2 top-0 bottom-0 w-[2px] bg-[#ffff00]"></div>
            <h3 className="text-sm font-['Orbitron'] font-bold text-[#ffff00] uppercase tracking-[0.15em] border-b border-[#ffff00]/30 pb-2 pl-2 flex items-center gap-2">
                <span className="w-2 h-2 bg-[#ffff00]"></span> 在线搜索
            </h3>
            
            <div className="flex gap-2 pl-2">
                <div className="relative flex-1 group">
                    <input 
                        type="text" 
                        value={searchKeyword}
                        onChange={e => setSearchKeyword(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                        placeholder="输入搜索关键字..."
                        className="w-full bg-[#0a0a0a] border border-white/20 text-white px-4 py-3 focus:outline-none focus:border-[#ffff00] transition-all font-['Rajdhani'] text-base placeholder-gray-600 relative z-10"
                    />
                </div>
                <button 
                    onClick={handleSearch}
                    disabled={isSearching}
                    className="bg-[#0a0a0a] border border-white/20 hover:border-[#ffff00] text-[#ffff00] hover:bg-[#ffff00]/5 font-['Orbitron'] font-bold px-8 py-3 flex items-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed group relative overflow-hidden"
                >
                    {isSearching ? <Loader2 size={16} className="animate-spin relative z-10 text-[#ffff00]" /> : <Search size={16} className="relative z-10 text-[#ffff00]" />}
                    <span className="relative z-10 tracking-widest text-[#ffff00]">搜索</span>
                </button>
            </div>

            {/* Results */}
            <div className="pl-2">
                {searchResults.length > 0 && (
                    <div className="space-y-3 mt-6">
                        {searchResults.map((res: any) => (
                            <div key={res.id} className="flex flex-col sm:flex-row sm:items-center justify-between bg-transparent border border-white/20 p-4 hover:border-white/50 transition-all gap-4 group">
                                <div className="flex flex-col overflow-hidden w-full sm:w-[75%]">
                                    <span className="text-base text-white truncate font-['Rajdhani'] font-bold tracking-wider" title={res.title || res.name}>{res.title || res.name}</span>
                                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-3 text-xs font-bold text-gray-500 uppercase tracking-widest font-['Orbitron']">
                                        <div className="border border-white/10 px-3 py-1 bg-white/5 flex items-center justify-center min-w-[60px]">
                                            <span className={
                                                (res.source || res.id?.split(':')[0])?.toLowerCase() === 'subhd' ? 'text-blue-400' :
                                                (res.source || res.id?.split(':')[0])?.toLowerCase() === 'srtku' ? 'text-green-400' :
                                                'text-gray-400'
                                            }>{res.source || res.id?.split(':')[0]}</span>
                                        </div>
                                        {res.format && (
                                            <span className="flex items-center gap-2">
                                                <div className="w-4 h-2.5 border border-white/50 rounded-sm"></div>
                                                <span className="text-gray-500">{res.format_normalized || res.format}</span>
                                            </span>
                                        )}
                                        {res.web_player && res.web_player.supported === false && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-orange-500" title="不兼容网页播放器">
                                                <span>⚠️ 不兼容网页播放器</span>
                                            </span>
                                        )}
                                        {res.language && (
                                            <span className="flex items-center gap-2 border-l border-white/10 pl-4">
                                                <span className="text-gray-400">{typeof res.language === 'string' ? res.language : (res.language?.label || res.language?.name || res.language?.code || '')}</span>
                                            </span>
                                        )}
                                        {res.rating && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4">
                                                <Star size={12} className="fill-yellow-400/50 text-yellow-500/50" />
                                                <span className="text-yellow-500/80">{res.rating}</span>
                                            </span>
                                        )}
                                        {res.uploader && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-500">
                                                👤 {res.uploader}
                                            </span>
                                        )}
                                        {res.download_number && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-500">
                                                <Download size={12} /> {res.download_number}
                                            </span>
                                        )}
                                        {res.quality && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-[#ffff00]/80">
                                                <Star size={12} className="fill-[#ffff00]/30" /> {res.quality}
                                            </span>
                                        )}
                                        {res.file_size && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-500">
                                                {res.file_size}
                                            </span>
                                        )}
                                        {res.update_time && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-gray-500">
                                                {res.update_time}
                                            </span>
                                        )}
                                        {res.season && (
                                            <span className="flex items-center gap-1 border-l border-white/10 pl-4 text-primary">
                                                S{res.season}{res.episode ? `E${res.episode}` : ''}
                                            </span>
                                        )}
                                    </div>
                                </div>
                                <button 
                                    onClick={() => handleBind(res.id)}
                                    disabled={isProcessing === res.id}
                                    className="self-end sm:self-auto shrink-0 flex items-center justify-center gap-2 bg-transparent border border-[#ffff00]/60 hover:bg-[#ffff00]/10 text-[#ffff00] px-6 py-2.5 text-xs font-['Orbitron'] font-bold tracking-[0.2em] transition-all disabled:opacity-50 min-w-[120px]"
                                >
                                    {isProcessing === res.id ? <Loader2 size={16} className="animate-spin text-[#ffff00]" /> : <Download size={14} className="text-[#ffff00]" />}
                                    <span className="text-[#ffff00]">绑定</span>
                                </button>
                            </div>
                        ))}
                    </div>
                )}
                
                {!isSearching && searchResults.length === 0 && searchKeyword && (
                    <div className="text-xs font-['Rajdhani'] tracking-wider text-gray-500 flex items-center gap-3 bg-[#0a0a0a] border border-white/5 p-4 mt-6">
                        <AlertCircle size={16} className="text-gray-500" />
                        系统正尝试通过外网索引寻找匹配字幕。调整关键字以获得更多结果。
                    </div>
                )}
            </div>

            {/* Upload Manually Option */}
            <div className="mt-8 border border-white/20 border-dashed flex flex-col items-center justify-center p-10 bg-black transition-colors">
                <Upload size={28} className="text-white mb-4" />
                <p className="text-[15px] font-bold text-white tracking-widest mb-6">持有本地字幕文件？</p>
                <label className="cursor-pointer bg-black border border-[#00f3ff] hover:bg-[#00f3ff]/10 text-[#00f3ff] px-10 py-3 text-sm font-bold tracking-[0.2em] transition-all">
                    <span>选择文件</span>
                    <input 
                        type="file" 
                        accept=".srt,.ass,.ssa,.vtt,.sub,.sup,.zip,.7z,.rar" 
                        className="hidden" 
                        onChange={async (e) => {
                            const file = e.target.files?.[0];
                            if (!file) return;
                            try {
                                setIsProcessing('upload');
                                const res = await movieService.uploadSubtitle(resourceId, file, true);
                                if (res && res.items) {
                                    setSubtitles(res.items);
                                    if (res.default_subtitle_id) setActiveDefaultId(res.default_subtitle_id);
                                    onSubtitlesChange(res.items, res.default_subtitle_id);
                                }
                                toast.success('上传并解析成功');
                            } catch (error: any) {
                                toast.error('上传失败: ' + error.message);
                            } finally {
                                setIsProcessing(null);
                            }
                        }}
                    />
                </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
