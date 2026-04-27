import React, { useState, useEffect, useMemo } from 'react';
import { FolderOpen, Folder, FileVideo, Database, Server, ChevronRight, ChevronDown, HardDrive, Loader2, Link, Plus, Check, X } from 'lucide-react';
import { movieService } from '../api';
import { Resource } from '../types';
import { toast } from '../utils';

interface ResourceTreeManagerProps {
  movieId: string;
}

export const ResourceTreeManager: React.FC<ResourceTreeManagerProps> = ({ movieId }) => {
  const [loading, setLoading] = useState(true);
  const [resourceGroups, setResourceGroups] = useState<import('../types').MovieResourceGroups | null>(null);
  const [expandedSeasons, setExpandedSeasons] = useState<Record<string, boolean>>({});

  // Remapping State
  const [remappingResId, setRemappingResId] = useState<string | null>(null);
  const [remapS, setRemapS] = useState('');
  const [remapE, setRemapE] = useState('');
  const [isSubmitingRemap, setIsSubmittingRemap] = useState(false);

  useEffect(() => {
    loadResources();
  }, [movieId]);

  const loadResources = async () => {
    setLoading(true);
    try {
      const data = await movieService.getResources(movieId);
      if (data) {
        setResourceGroups(data);
        
        // Auto expand all seasons
        const initialExpanded: Record<string, boolean> = { 'unknown': true };
        if (data.groups?.seasons) {
            data.groups.seasons.forEach(sg => {
                initialExpanded[String(sg.season)] = true;
            });
        }
        setExpandedSeasons(initialExpanded);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const submitRemap = async (resId: string) => {
    const s = parseInt(remapS);
    const e = parseInt(remapE);
    if (isNaN(s) || isNaN(e)) {
      toast.error('非法注入！季/集必须是数字。');
      return;
    }

    setIsSubmittingRemap(true);
    try {
      const items = [{
        resource_id: resId,
        season: s,
        episode: e
      }];
      await movieService.updateResourcesMetadata(movieId, items);
      setRemappingResId(null);
      await loadResources();
    } catch (err) {
      console.error(err);
      toast.error('重新挂载物理卷失败');
    } finally {
      setIsSubmittingRemap(false);
    }
  };

  const toggleSeason = (s: string) => {
    setExpandedSeasons(prev => ({ ...prev, [s]: !prev[s] }));
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return '未知体积';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return gb.toFixed(2) + ' GB';
    const mb = bytes / (1024 * 1024);
    return mb.toFixed(2) + ' MB';
  };

  const resources = resourceGroups?.items || [];
  const standaloneItems = useMemo(() => {
    if (!resourceGroups?.groups?.standalone?.resource_ids) return [];
    return resourceGroups.groups.standalone.resource_ids.map(id => resources.find(r => r.id === id)).filter(Boolean) as import('../types').Resource[];
  }, [resourceGroups, resources]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center p-24 text-primary">
        <Loader2 size={48} className="animate-spin mb-6" />
        <p className="tracking-widest font-mono text-lg animate-pulse">正在挂载物理层数据存储器，扫描逻辑碎片中...</p>
      </div>
    );
  }
  const seasonGroups = resourceGroups?.groups?.seasons || [];

  return (
    <div className="font-mono space-y-4 animate-in fade-in zoom-in-95 duration-300">
      <div className="flex items-center justify-between border-b border-primary-30 pb-4 mb-6">
        <div className="flex items-center gap-3">
          <HardDrive size={24} className="text-primary-70" />
          <h3 className="font-bold tracking-widest text-primary text-xl">全息物理资源拓扑树 (Resource Topology)</h3>
        </div>
        <div className="text-xs text-primary-50 px-3 py-1 bg-primary-10 border border-primary-50">
          发现数据块: {resources.length} 个
        </div>
      </div>
      
      <div className="bg-[#050508] border border-primary-30 p-6 shadow-[inset_0_0_30px_rgba(0,0,0,0.8)] min-h-[400px]">
        {resources.length === 0 ? (
          <div className="text-primary-50 text-center py-24 flex flex-col items-center gap-6">
            <div className="relative">
              <Database size={64} className="opacity-20" />
              <Link size={32} className="absolute -bottom-2 -right-2 opacity-50 text-red-500 mix-blend-screen animate-pulse" />
            </div>
            <div className="space-y-2">
              <p className="text-lg tracking-widest text-primary">神经链路断开</p>
              <p className="text-sm opacity-50">未检测到该实体的关联物理视频文件碎片。请检查挂载盘。</p>
            </div>
          </div>
        ) : (
          <div className="space-y-2 text-sm">
            {/* Main Root node */}
            <div className="flex items-center gap-3 text-primary font-bold bg-primary-10 p-2 border border-primary-50/30">
              <Server size={18} />
              <span className="tracking-widest">/mnt/datastore/entity_{movieId.padStart(6, '0')}</span>
            </div>
            
            <div className="pl-6 border-l-2 border-primary-30/50 ml-3 pt-3 pb-6 space-y-6">
              
              {/* Render Seasons from API */}
              {seasonGroups.map(sg => {
                const s = String(sg.season);
                const seasonItems = sg.resource_ids?.map(id => resources.find(r => r.id === id)).filter(Boolean) as import('../types').Resource[] || sg.items || [];
                return (
                  <div key={s} className="space-y-2">
                    <div 
                      className="flex items-center gap-3 cursor-pointer hover:text-white text-primary transition-colors group"
                      onClick={() => toggleSeason(s)}
                    >
                      {expandedSeasons[s] ? <ChevronDown size={18} className="text-primary-50" /> : <ChevronRight size={18} className="text-primary-50" />}
                      {expandedSeasons[s] ? <FolderOpen size={18} className="text-primary-70 group-hover:text-primary fill-primary-20" /> : <Folder size={18} className="text-primary-70 group-hover:text-primary fill-primary-10" />}
                      <span className="font-bold text-lg tracking-widest text-primary-90">
                        {sg.display_title || `Season ${s.padStart(2, '0')}`}
                      </span>
                      <span className="text-xs text-primary-50 ml-2 bg-primary-10 px-2 py-0.5 rounded-sm">[{seasonItems.length} BLOCKS]</span>
                    </div>
                    
                    {expandedSeasons[s] && (
                      <div className="pl-8 border-l border-dashed border-primary-30/50 ml-3 py-2 space-y-1">
                        {seasonItems.map(res => (
                          <div key={res.id} className="flex items-center gap-3 text-primary-70 hover:text-white hover:bg-primary-10 p-1.5 group transition-colors relative cursor-crosshair">
                            <div className="absolute left-[-32px] top-1/2 w-4 h-px bg-primary-30/50"></div>
                            <FileVideo size={16} className="opacity-50 group-hover:opacity-100 group-hover:text-primary flex-shrink-0" />
                            <span className="truncate flex-1 tracking-wide">
                                {(res.resource_info?.display?.episode ?? res.episode) !== undefined ? `E${String(res.resource_info?.display?.episode ?? res.episode).padStart(2, '0')} - ` : ''}
                                {res.resource_info?.file?.filename || res.filename}
                            </span>
                            
                            <div className="flex items-center gap-3 opacity-60 group-hover:opacity-100 font-mono text-xs">
                               <span className="text-blue-400 bg-blue-900/20 px-1.5 py-0.5 rounded-sm whitespace-nowrap">
                                {(() => {
                                  const label = res.display_label || res.quality_label || res.resource_info?.technical?.video_resolution_badge_label || res.resource_info?.technical?.video_resolution_label || res.media_info?.resolution;
                                  return (label && label.toUpperCase() !== 'UNKNOWN') ? label : '';
                                })()}
                              </span>
                              {(res.resource_info?.technical?.flag_is_hdr || res.media_info?.hdr) && (
                                <span className="text-yellow-500 bg-yellow-900/20 px-1.5 py-0.5 rounded-sm whitespace-nowrap font-bold">
                                  {(() => {
                                    const hdr = res.resource_info?.technical?.video_dynamic_range_label || res.media_info?.hdr || 'HDR';
                                    return (hdr && hdr.toUpperCase() !== 'UNKNOWN') ? hdr.toUpperCase() : 'HDR';
                                  })()}
                                </span>
                              )}
                              <span className="text-green-400 bg-green-900/20 px-1.5 py-0.5 rounded-sm whitespace-nowrap min-w-[80px] text-right">
                                {formatSize(res.size_bytes)}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Render Standalone / Unmapped from API */}
              {standaloneItems.length > 0 && (
                <div className="space-y-2 mt-8 pt-4 border-t border-dashed border-red-500/30">
                  <div 
                    className="flex items-center gap-3 cursor-pointer hover:text-red-300 text-red-500 transition-colors group"
                    onClick={() => toggleSeason('unknown')}
                  >
                    {expandedSeasons['unknown'] ? <ChevronDown size={18} className="text-red-500/70" /> : <ChevronRight size={18} className="text-red-500/70" />}
                    {expandedSeasons['unknown'] ? <FolderOpen size={18} className="text-red-400 group-hover:text-red-300 fill-red-900/30" /> : <Folder size={18} className="text-red-400 group-hover:text-red-300 fill-red-900/20" />}
                    <span className="font-bold text-lg tracking-widest text-red-400">独立资源 / 未分类 (STANDALONE_BLOCKS)</span>
                    <span className="text-xs text-red-400/70 ml-2 bg-red-500/10 border border-red-500/30 px-2 py-0.5 rounded-sm">[{standaloneItems.length} BLOCKS]</span>
                  </div>

                  {expandedSeasons['unknown'] && (
                    <div className="pl-8 border-l border-dashed border-red-500/30 ml-3 py-2 space-y-1">
                      {standaloneItems.map(res => (
                        <div key={res.id} className="flex flex-col gap-2 relative">
                          <div className="flex items-center gap-3 text-red-400/70 hover:text-red-300 hover:bg-red-500/10 p-1.5 group transition-colors relative cursor-crosshair">
                            <div className="absolute left-[-32px] top-1/2 w-4 h-px bg-red-500/30"></div>
                            <FileVideo size={16} className="opacity-50 group-hover:opacity-100 flex-shrink-0" />
                            <span className="truncate flex-1 tracking-wide">{res.resource_info?.file?.filename || res.filename}</span>
                            
                            <div className="flex items-center gap-3 opacity-60 group-hover:opacity-100 font-mono text-xs">
                              <span className="text-red-300 bg-red-900/20 px-1.5 py-0.5 rounded-sm whitespace-nowrap">
                                {(() => {
                                  const label = res.display_label || res.quality_label || res.resource_info?.technical?.video_resolution_badge_label || res.resource_info?.technical?.video_resolution_label || res.media_info?.resolution;
                                  return (label && label.toUpperCase() !== 'UNKNOWN') ? label : '';
                                })()}
                              </span>
                              {(res.resource_info?.technical?.flag_is_hdr || res.media_info?.hdr) && (
                                <span className="text-yellow-500 bg-yellow-900/20 px-1.5 py-0.5 rounded-sm whitespace-nowrap font-bold ml-1">
                                  {(() => {
                                    const hdr = res.resource_info?.technical?.video_dynamic_range_label || res.media_info?.hdr || 'HDR';
                                    return (hdr && hdr.toUpperCase() !== 'UNKNOWN') ? hdr.toUpperCase() : 'HDR';
                                  })()}
                                </span>
                              )}
                              <span className="text-red-300 bg-red-900/20 px-1.5 py-0.5 rounded-sm whitespace-nowrap min-w-[80px] text-right">
                                {formatSize(res.size_bytes)}
                              </span>
                            </div>
                            
                            {/* Actions */}
                            {(!remappingResId || remappingResId !== res.id) && (
                              <button 
                                onClick={() => {
                                  setRemappingResId(res.id);
                                  setRemapS('');
                                  setRemapE('');
                                }}
                                className="ml-2 px-2 py-0.5 border border-red-500 text-red-500 hover:bg-red-500 hover:text-black flex items-center gap-1 text-xs font-bold transition-colors shadow-[0_0_10px_rgba(239,68,68,0.2)]"
                                title="手动强制注入季集"
                              >
                                <Plus size={12} /> 强制注入
                              </button>
                            )}
                          </div>
                          
                          {/* Remap Form Panel */}
                          {remappingResId === res.id && (
                            <div className="ml-8 mr-2 p-3 bg-black border border-red-500 box-shadow-neon flex items-center gap-4 animate-in fade-in slide-in-from-top-2">
                              <div className="text-red-400 text-xs tracking-widest font-bold">目标路由:</div>
                              <div className="flex items-center gap-2">
                                <span className="text-red-500 text-sm">S</span>
                                <input 
                                  type="number" 
                                  value={remapS} 
                                  onChange={e => setRemapS(e.target.value)}
                                  placeholder="01"
                                  className="w-12 bg-transparent border-b border-red-500/50 focus:border-red-500 focus:outline-none text-red-100 placeholder:text-red-900/50 text-center py-1"
                                />
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-red-500 text-sm">E</span>
                                <input 
                                  type="number" 
                                  value={remapE} 
                                  onChange={e => setRemapE(e.target.value)}
                                  placeholder="01"
                                  className="w-12 bg-transparent border-b border-red-500/50 focus:border-red-500 focus:outline-none text-red-100 placeholder:text-red-900/50 text-center py-1"
                                />
                              </div>
                              <div className="flex-1"></div>
                              <button 
                                onClick={() => submitRemap(res.id)}
                                disabled={isSubmitingRemap}
                                className="px-3 py-1 bg-red-900/30 text-red-400 hover:bg-red-500 hover:text-black border border-red-500 flex items-center gap-1 text-xs transition-colors disabled:opacity-50"
                              >
                                {isSubmitingRemap ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} 确认挂载
                              </button>
                              <button 
                                onClick={() => setRemappingResId(null)}
                                className="p-1 hover:text-white transition-colors text-red-500"
                              >
                                <X size={16} />
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
