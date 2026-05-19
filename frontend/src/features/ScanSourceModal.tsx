import React, { useState, useEffect } from 'react';
import { Zap, X, MapPin, Search, Folder, ChevronRight, Loader2, FolderSearch, Settings2 } from 'lucide-react';
import { storageService, movieService } from '../api';
import { toast } from '../utils';

interface ScanSourceModalProps {
  sourceId: number;
  sourceName: string;
  onClose: () => void;
}

export const ScanSourceModal: React.FC<ScanSourceModalProps> = ({ sourceId, sourceName, onClose }) => {
  const [targetPath, setTargetPath] = useState('');
  const [scrapeEnabled, setScrapeEnabled] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [contentType, setContentType] = useState<string>('');

  const [isBrowsing, setIsBrowsing] = useState(false);
  const [browsePath, setBrowsePath] = useState('/');
  const [browseItems, setBrowseItems] = useState<import('../types/index').FileItem[]>([]);
  const [isBrowseLoading, setIsBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  const [providers, setProviders] = useState<{key: string; name: string}[]>([]);
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);

  const fetchBrowseItems = async (path: string) => {
    setIsBrowseLoading(true);
    setBrowseError(null);
    const result = await storageService.getSourceBrowse(sourceId, path);
    if (result.error) {
      setBrowseError(result.error);
    } else {
      setBrowseItems(result.items || []);
    }
    setIsBrowseLoading(false);
  };

  useEffect(() => {
    if (isBrowsing) {
      fetchBrowseItems(browsePath);
    }
  }, [isBrowsing, browsePath]);

  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const catalog = await movieService.getMetadataProviders();
        if (catalog && catalog.providers) {
          // manual_only provider（如 tencent_video）只允许在单片手动匹配中使用，
          // 不能进入自动扫描的 provider_order。
          const automatable = catalog.providers.filter(p => !p.manual_only);
          setProviders(automatable.map(p => ({ key: p.key!, name: p.name! })));
          if (catalog.default_order) {
            setSelectedProviders(catalog.default_order.filter(k => automatable.some(p => p.key === k)));
          } else {
            setSelectedProviders(automatable.map(p => p.key!));
          }
        }
      } catch (err) {
        console.error("Failed to fetch providers", err);
      }
    };
    fetchProviders();
  }, []);

  const handleLevelUp = () => {
    if (browsePath === '/') return;
    const parts = browsePath.split('/').filter(Boolean);
    parts.pop();
    setBrowsePath('/' + parts.join('/'));
  };

  const handleSelectPath = (path: string) => {
    // Strip leading slash if needed or just keep it
    setTargetPath(path === '/' ? '' : path.replace(/^\//, ''));
    setIsBrowsing(false);
  };

  const toggleProvider = (key: string) => {
    setSelectedProviders(prev => 
      prev.includes(key) ? prev.filter(p => p !== key) : [...prev, key]
    );
  };

  const handleScan = async () => {
    setIsScanning(true);
    const options: any = {
      scrape_enabled: scrapeEnabled,
    };
    if (targetPath.trim() !== '') options.target_path = targetPath.trim();
    if (contentType !== '') options.content_type = contentType;
    if (scrapeEnabled && selectedProviders.length > 0) {
      options.provider_order = selectedProviders;
    }

    const success = await storageService.scanSource(sourceId, options);
    if (success) {
      window.dispatchEvent(new CustomEvent("cyber:scan:started"));
      toast.success(`[${sourceName}] 定制扫描程序已推入队列`);
      onClose();
    } else {
      toast.error('触发扫描指令被主机拒绝');
    }
    setIsScanning(false);
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#0a0a12] border border-cyan-500/30 w-full max-w-md flex flex-col font-mono text-cyan-50 shadow-[0_0_30px_rgba(6,182,212,0.15)] max-h-[90vh]">
        {/* Header */}
        <div className="p-4 border-b border-cyan-500/30 flex justify-between items-center bg-cyan-500/10 shrink-0">
          <div className="flex items-center gap-2 text-cyan-400">
            <Zap size={20} />
            <h3 className="font-bold tracking-widest text-lg">定向光学扫描程序</h3>
          </div>
          <button onClick={onClose} className="text-cyan-500 hover:text-white hover:bg-red-500/80 p-1 transition-colors rounded">
            <X size={24} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6 overflow-y-auto">
          <div className="space-y-2">
            <label className="text-xs text-cyan-500/70 uppercase tracking-widest flex items-center justify-between">
              <div className="flex items-center gap-2"><MapPin size={14} /> 增量下钻目标层级 (Target Path)</div>
              <button 
                onClick={() => setIsBrowsing(!isBrowsing)}
                className="text-cyan-400 hover:text-cyan-300 flex items-center gap-1 bg-cyan-500/10 px-2 py-1 rounded transition-colors"
                title="浏览目录"
              >
                <FolderSearch size={14} /> 浏览
              </button>
            </label>
            <input 
              type="text" 
              value={targetPath}
              onChange={e => setTargetPath(e.target.value)}
              placeholder="例如: 电影/2023 或留空以全量扫描"
              className="w-full bg-black/50 border border-cyan-500/30 focus:border-cyan-400 focus:outline-none p-3 text-cyan-50 font-sans placeholder-cyan-900/50 transition-colors"
            />
          </div>

          {isBrowsing && (
            <div className="bg-black/40 border border-cyan-500/20 p-2 max-h-60 flex flex-col mt-2">
              <div className="flex items-center gap-2 mb-2 px-2 pb-2 border-b border-cyan-500/10">
                <button 
                  onClick={handleLevelUp}
                  disabled={browsePath === '/'}
                  className="text-cyan-500 hover:text-cyan-300 disabled:opacity-30 disabled:cursor-not-allowed px-2 py-1"
                >
                  <ChevronRight size={16} className="rotate-180" />
                </button>
                <span className="text-sm text-cyan-100 truncate flex-1">{browsePath}</span>
                <button 
                  onClick={() => handleSelectPath(browsePath)}
                  className="text-xs bg-cyan-500/20 hover:bg-cyan-500/40 text-cyan-400 px-2 py-1 transition-colors"
                >
                  选择此目录
                </button>
              </div>
              
              <div className="flex-1 overflow-y-auto">
                {isBrowseLoading ? (
                  <div className="flex items-center justify-center p-4 text-cyan-500/50">
                    <Loader2 size={18} className="animate-spin" />
                  </div>
                ) : browseError ? (
                  <div className="text-red-400/80 text-sm p-4 text-center">
                    {browseError}
                  </div>
                ) : browseItems.filter(i => i.type === 'dir').length === 0 ? (
                  <div className="text-cyan-500/50 text-sm p-4 text-center">空目录</div>
                ) : (
                  <div className="space-y-1 p-1">
                    {browseItems.filter(i => i.type === 'dir').map((item, idx) => (
                      <div 
                        key={idx} 
                        className="flex items-center gap-2 p-2 hover:bg-cyan-500/10 cursor-pointer text-sm text-cyan-100 transition-colors group"
                        onClick={() => setBrowsePath(item.path)}
                      >
                        <Folder size={16} className="text-cyan-500/70 group-hover:text-cyan-400" />
                        <span className="truncate">{item.name}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <label className="text-xs text-cyan-500/70 uppercase tracking-widest flex items-center gap-2">
              <Search size={14} /> 资产约束模型 (Content Type)
            </label>
            <select
              value={contentType}
              onChange={e => setContentType(e.target.value)}
              className="w-full bg-black/50 border border-cyan-500/30 focus:border-cyan-400 focus:outline-none py-2 pr-4 pl-3 text-cyan-50 font-sans transition-colors cursor-pointer appearance-none"
            >
              <option value="">自动推理 (Auto-Inference)</option>
              <option value="movie">强制按【电影】模型解析</option>
              <option value="tv">强制按【剧集】模型解析</option>
            </select>
          </div>

          <div className="space-y-4">
            <label className="flex items-center gap-3 cursor-pointer p-3 border border-cyan-500/20 bg-cyan-500/5 hover:bg-cyan-500/10 transition-colors">
              <input 
                type="checkbox" 
                checked={scrapeEnabled}
                onChange={e => setScrapeEnabled(e.target.checked)}
                className="accent-cyan-500 w-4 h-4 cursor-pointer"
              />
              <div className="flex flex-col">
                <span className="text-sm text-cyan-100 uppercase tracking-wider">执行元数据神经节点映射 (Scrape)</span>
                <span className="text-xs text-cyan-500/50">如关闭，仅进行物理文件入库拓扑</span>
              </div>
            </label>

            {scrapeEnabled && providers.length > 0 && (
              <div className="p-3 border border-cyan-500/20 bg-black/40 space-y-3 animate-in fade-in slide-in-from-top-2">
                <label className="text-xs text-cyan-500/70 uppercase tracking-widest flex items-center gap-2">
                  <Settings2 size={14} /> 刮削节点优先级组网 (Provider Order)
                </label>
                <div className="flex flex-wrap gap-2">
                  {providers.map(p => (
                    <button
                      key={p.key}
                      onClick={() => toggleProvider(p.key)}
                      className={`px-2 py-1 text-xs border transition-colors ${
                        selectedProviders.includes(p.key)
                          ? 'border-cyan-500 bg-cyan-500/20 text-cyan-100'
                          : 'border-cyan-500/20 bg-black text-cyan-500/50 hover:border-cyan-500/50'
                      }`}
                    >
                      {p.name || p.key}
                    </button>
                  ))}
                </div>
                {selectedProviders.length === 0 && (
                  <p className="text-xs text-red-400">警告: 未选择任何刮削节点，将无法进行元数据识别</p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-cyan-500/30 bg-black/40 flex justify-end gap-3 shrink-0">
          <button 
            onClick={onClose}
            className="px-4 py-2 border border-cyan-500/30 text-cyan-500/70 hover:text-cyan-400 hover:bg-cyan-500/10 transition-colors text-sm uppercase tracking-widest"
          >
            终止 (Abort)
          </button>
          <button 
            onClick={handleScan}
            disabled={isScanning}
            className="px-6 py-2 bg-cyan-500/80 hover:bg-cyan-400 text-black font-bold flex items-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed uppercase tracking-widest"
          >
            {isScanning ? '初始化...' : '投放信标 (Engage)'}
          </button>
        </div>
      </div>
    </div>
  );
};
