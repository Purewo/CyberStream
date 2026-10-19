import React, { useState } from 'react';
import { Search, Loader2, Check, X, Database, AlertTriangle, ArrowLeft } from 'lucide-react';
import { movieService } from '../api';
import { toast } from '../utils';
import { getApiBase } from '../platform';

const resolveCandidatePoster = (cand: any): string | null => {
  const url = cand.poster_url || cand.poster;
  if (url) {
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    if (url.startsWith('/api/')) return `${getApiBase()}${url.substring(4)}`;
    return url;
  }
  if (cand.poster_path) return `https://image.tmdb.org/t/p/w200${cand.poster_path}`;
  return null;
};

const resolvePreviewPoster = (url?: string | null): string | null => {
  if (!url) return null;
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  if (url.startsWith('/api/')) return `${getApiBase()}${url.substring(4)}`;
  if (url.startsWith('/v1/')) return `${getApiBase()}${url}`;
  return url;
};

const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  original_title: '原名',
  year: '年份',
  overview: '简介',
  description: '简介',
  poster_url: '海报',
  cover: '海报',
  backdrop_url: '背景图',
  background_cover: '背景图',
  country: '国家',
  director: '导演',
  category: '分类',
  actors: '主演',
  tmdb_id: 'TMDB ID',
  rating: '评分',
  scraper_source: '来源',
};

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
  const [previewingId, setPreviewingId] = useState<string | null>(null);

  const [providers, setProviders] = useState<{key: string, name: string}[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>('');

  // dry-run 预览状态
  const [preview, setPreview] = useState<any>(null);
  const [previewSourceCandidate, setPreviewSourceCandidate] = useState<any>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [missingPosterPrompt, setMissingPosterPrompt] = useState(false);
  // 用户在 diff 里取消勾选的字段（会从 metadata_unlocked_fields 中去掉，让后端跳过该字段）
  const [excludedFields, setExcludedFields] = useState<Set<string>>(new Set());

  React.useEffect(() => {
    movieService.getMetadataProviders().then(catalog => {
      if (catalog?.providers) {
        setProviders(catalog.providers);
      }
    }).catch(console.error);
  }, []);

  const handleSearch = async () => {
    setIsSearching(true);
    try {
      const results = await movieService.searchMetadataCandidates(
        movieId,
        query,
        year === '' ? undefined : Number(year),
        selectedProvider ? selectedProvider : undefined
      );
      const items = results?.items || [];
      if (items.length === 0) {
        toast.info('未在外部网络找到匹配节点');
      } else {
        toast.success(`提取到 ${items.length} 个候选节点`);
      }
      setCandidates(items);
    } catch (e) {
      console.error(e);
      toast.error('检索神经元网络失败');
    } finally {
      setIsSearching(false);
    }
  };

  const handlePreview = async (candidate: any, candidateId: string, provider: string, mediaType: 'movie' | 'tv') => {
    setPreviewingId(candidateId);
    try {
      const data = await movieService.previewMetadataMatch(movieId, candidateId, provider, unlockedFields, mediaType);
      if (data) {
        setPreview(data);
        setPreviewSourceCandidate(candidate);
        setExcludedFields(new Set());
      } else {
        toast.error('预览失败，请检查后端连接或候选节点是否仍可用');
      }
    } catch (e) {
      console.error(e);
      toast.error('预览时发生致命错误');
    } finally {
      setPreviewingId(null);
    }
  };

  const performApply = async (allowMissingPoster: boolean) => {
    if (!preview?.apply_payload) return;
    setIsApplying(true);
    try {
      // 基于 apply_payload，按用户在 diff 里取消勾选的字段，把 metadata_unlocked_fields 收窄
      const basePayload = { ...preview.apply_payload };
      const baseUnlocked: string[] = (basePayload.metadata_unlocked_fields as string[] | undefined)
        || (preview.diff?.unlocked_fields as string[] | undefined)
        || [];
      if (excludedFields.size > 0) {
        basePayload.metadata_unlocked_fields = baseUnlocked.filter(f => !excludedFields.has(f));
      }

      const result = await movieService.applyMetadataMatch(movieId, basePayload, { allowMissingPoster });
      if (result.ok === true) {
        toast.success(`成功绑定！系统档案已被 [${result.movie.title}] 覆盖`);
        onMatch(result.movie);
        return;
      }
      // result.ok === false 后才有 status/msg
      const failure = result as { ok: false; status: number; code?: number; msg?: string };
      // 处理 409 缺海报：UI 内联二次确认（iframe 中 window.confirm 不可用）
      if (failure.status === 409 && !allowMissingPoster) {
        setMissingPosterPrompt(true);
        toast.warning('当前候选与影片均无海报，需要二次确认才能写入');
        return;
      }
      toast.error(`档案覆写失败：${failure.msg || `HTTP ${failure.status}`}`);
    } catch (e) {
      console.error(e);
      toast.error('应用时发生致命错误');
    } finally {
      setIsApplying(false);
    }
  };

  const handleApply = () => performApply(false);
  const handleConfirmMissingPoster = () => {
    setMissingPosterPrompt(false);
    performApply(true);
  };
  const handleBackToList = () => { setPreview(null); setPreviewSourceCandidate(null); setMissingPosterPrompt(false); setExcludedFields(new Set()); };

  const toggleFieldInclusion = (field: string) => {
    setExcludedFields(prev => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field); else next.add(field);
      return next;
    });
  };

  const renderDiffValue = (val: unknown): string => {
    if (val === null || val === undefined || val === '') return '—';
    if (Array.isArray(val)) return val.length > 0 ? val.join(', ') : '—';
    if (typeof val === 'object') return JSON.stringify(val);
    return String(val);
  };

  if (preview) {
    const fields = preview.diff?.fields || [];
    const summary = preview.diff?.summary || {};
    const warnings = preview.warnings || [];
    const currentItem = preview.current || {};
    const previewItem = preview.preview || {};
    const effectiveWriteCount = fields.filter((f: any) => f.will_apply && !f.locked && !excludedFields.has(f.field)).length;

    // 兜底：当后端 preview.preview 里某些字段没填全（GPT5.5 已知场景），从 diff.fields 里捞 preview_value
    const getFromDiff = (...fieldNames: string[]): unknown => {
      for (const name of fieldNames) {
        const f = fields.find((x: any) => x.field === name);
        if (f && f.preview_value !== null && f.preview_value !== undefined && f.preview_value !== '') return f.preview_value;
      }
      return undefined;
    };
    const previewPoster = previewItem.poster_url || (getFromDiff('cover', 'poster_url') as string | undefined) || (previewSourceCandidate?.poster_url as string | undefined) || (previewSourceCandidate?.poster as string | undefined);
    const previewOverview = previewItem.overview || (getFromDiff('description', 'overview') as string | undefined) || (previewSourceCandidate?.overview as string | undefined);

    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
        <div className="bg-[#0a0a12] border border-primary-50 w-full max-w-4xl max-h-[90vh] flex flex-col font-mono text-primary box-shadow-neon">
          <div className="p-4 border-b border-primary-30 flex justify-between items-center bg-primary-10">
            <div className="flex items-center gap-2">
              <Database size={20} />
              <h3 className="font-bold tracking-widest text-lg">变更预览 / DRY-RUN</h3>
              {preview.identity?.changed && <span className="text-xs px-2 py-0.5 border border-yellow-500/50 text-yellow-400 bg-yellow-500/10">身份将变更</span>}
            </div>
            <button onClick={onClose} className="hover:text-white hover:bg-red-500 p-1 transition-colors">
              <X size={24} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-[#050505]/50 space-y-4">
            {warnings.length > 0 && (
              <div className="border border-yellow-500/40 bg-yellow-500/5 p-3 space-y-1">
                {warnings.map((w: any, idx: number) => (
                  <div key={idx} className="flex items-start gap-2 text-sm text-yellow-300">
                    <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                    <span><span className="text-yellow-500 font-bold">[{w.code || w.severity || '提醒'}]</span> {w.message}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="border border-primary-30 bg-black/40 p-3">
                <div className="text-xs text-primary-50 mb-2 tracking-widest">当前</div>
                <div className="flex gap-3">
                  <div className="w-20 h-28 bg-primary-20 flex-shrink-0 overflow-hidden border border-primary-30">
                    {resolvePreviewPoster(currentItem.poster_url) ? (
                      <img src={resolvePreviewPoster(currentItem.poster_url)!} alt="current" className="w-full h-full object-cover" referrerPolicy="no-referrer" />
                    ) : (<div className="w-full h-full flex items-center justify-center text-[10px] text-primary-50">无图像</div>)}
                  </div>
                  <div className="flex-1 min-w-0 text-xs text-primary-70 font-sans space-y-1">
                    <div className="text-white font-bold truncate">{currentItem.title || '—'}</div>
                    <div>原名: {currentItem.original_title || '—'}</div>
                    <div>年份: {currentItem.year || '—'}</div>
                    <div>TMDB: {currentItem.tmdb_id || '—'}</div>
                  </div>
                </div>
                {currentItem.overview && (
                  <div className="mt-3 text-[11px] text-primary-50 line-clamp-3 font-sans leading-relaxed">{currentItem.overview}</div>
                )}
              </div>

              <div className="border border-primary bg-primary-10 p-3">
                <div className="text-xs text-primary mb-2 tracking-widest">应用后</div>
                <div className="flex gap-3">
                  <div className="w-20 h-28 bg-primary-20 flex-shrink-0 overflow-hidden border border-primary">
                    {resolvePreviewPoster(previewPoster) ? (
                      <img src={resolvePreviewPoster(previewPoster)!} alt="preview" className="w-full h-full object-cover" referrerPolicy="no-referrer" />
                    ) : (<div className="w-full h-full flex items-center justify-center text-[10px] text-primary-50">无图像</div>)}
                  </div>
                  <div className="flex-1 min-w-0 text-xs text-primary-70 font-sans space-y-1">
                    <div className="text-white font-bold truncate">{previewItem.title || '—'}</div>
                    <div>原名: {previewItem.original_title || '—'}</div>
                    <div>年份: {previewItem.year || '—'}</div>
                    <div>TMDB: {previewItem.tmdb_id || '—'}</div>
                  </div>
                </div>
                {previewOverview ? (
                  <div className="mt-3 text-[11px] text-primary-70 line-clamp-3 font-sans leading-relaxed">{String(previewOverview)}</div>
                ) : null}
              </div>
            </div>

            <div className="border border-primary-30 bg-black/40">
              <div className="px-3 py-2 border-b border-primary-30 flex justify-between items-center text-xs">
                <span className="tracking-widest">字段差异 · 取消勾选可跳过该字段写入</span>
                <span className="text-primary-50 font-sans">
                  将写入 <span className="text-primary">{effectiveWriteCount}</span> / {summary.will_apply_count || 0} 项 · 已锁定阻止 <span className="text-yellow-400">{summary.blocked_count || 0}</span> 项
                </span>
              </div>
              <div className="max-h-[40vh] overflow-y-auto custom-scrollbar">
                {fields.length === 0 ? (
                  <div className="p-4 text-center text-xs text-primary-50">无变化</div>
                ) : (
                  <table className="w-full text-xs font-sans">
                    <thead className="sticky top-0 bg-[#0a0a12] z-10">
                      <tr className="text-primary-50 border-b border-primary-30">
                        <th className="text-left px-3 py-2 w-10">应用</th>
                        <th className="text-left px-3 py-2 w-24">字段</th>
                        <th className="text-left px-3 py-2">当前值</th>
                        <th className="text-left px-3 py-2">新值</th>
                        <th className="text-left px-3 py-2 w-20">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fields.map((f: any, idx: number) => {
                        const isExcluded = excludedFields.has(f.field);
                        const isWritable = f.will_apply && !f.locked;
                        const effectivelyWriting = isWritable && !isExcluded;
                        return (
                          <tr key={idx} className={`border-b border-primary-30/30 ${effectivelyWriting ? 'bg-primary-10/40' : ''} ${isExcluded ? 'opacity-50' : ''}`}>
                            <td className="px-3 py-2">
                              {isWritable ? (
                                <input
                                  type="checkbox"
                                  checked={!isExcluded}
                                  onChange={() => toggleFieldInclusion(f.field)}
                                  className="accent-primary cursor-pointer"
                                  title="取消勾选则后端跳过该字段写入"
                                />
                              ) : (
                                <span className="text-primary-30">—</span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-primary whitespace-nowrap">{FIELD_LABELS[f.field] || f.field}</td>
                            <td className="px-3 py-2 text-primary-70 break-words"><div className="line-clamp-2">{renderDiffValue(f.current_value)}</div></td>
                            <td className="px-3 py-2 text-white break-words"><div className="line-clamp-2">{renderDiffValue(f.preview_value)}</div></td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              {f.locked ? (
                                <span className="text-yellow-400">已锁定</span>
                              ) : isExcluded ? (
                                <span className="text-primary-50">跳过</span>
                              ) : f.will_apply ? (
                                <span className="text-primary">写入</span>
                              ) : f.changed ? (
                                <span className="text-primary-50">差异</span>
                              ) : (
                                <span className="text-primary-50">不变</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          <div className="p-4 border-t border-primary-30 bg-primary-10 flex justify-between items-center gap-4">
            <button onClick={handleBackToList} disabled={isApplying} className="flex items-center gap-2 text-primary hover:text-white px-3 py-2 transition-colors disabled:opacity-50">
              <ArrowLeft size={16} /> 返回候选列表
            </button>
            {missingPosterPrompt ? (
              <div className="flex items-center gap-3">
                <span className="text-xs text-yellow-300 flex items-center gap-1">
                  <AlertTriangle size={14} /> 候选与当前影片都没有海报，应用后将无可见封面
                </span>
                <button
                  onClick={handleConfirmMissingPoster}
                  disabled={isApplying}
                  className="bg-yellow-500 text-black px-4 py-2 font-bold flex items-center justify-center gap-2 hover:bg-yellow-400 transition-colors disabled:opacity-50"
                >
                  {isApplying ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                  仍然写入
                </button>
              </div>
            ) : (
              <button
                onClick={handleApply}
                disabled={isApplying || effectiveWriteCount === 0}
                className="bg-primary text-black px-6 py-2 font-bold flex items-center justify-center gap-2 hover:bg-primary-70 transition-colors disabled:bg-primary-30 disabled:cursor-not-allowed"
              >
                {isApplying ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                {isApplying ? '写入中' : `确认覆盖 (${effectiveWriteCount} 项)`}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#0a0a12] border border-primary-50 w-full max-w-3xl max-h-[85vh] flex flex-col font-mono text-primary box-shadow-neon">
        {/* Header */}
        <div className="p-4 border-b border-primary-30 flex justify-between items-center bg-primary-10">
          <div className="flex items-center gap-2">
            <Database size={20} />
            <h3 className="font-bold tracking-widest text-lg">外部神经源精准匹配</h3>
          </div>
          <button onClick={onClose} className="hover:text-white hover:bg-red-500 p-1 transition-colors">
            <X size={24} />
          </button>
        </div>

        {/* Search Bar */}
        <div className="p-6 border-b border-primary-30 bg-[#050505] space-y-4">
          <div className="flex gap-4 items-end">
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
            <div className="w-24 space-y-1">
              <label className="text-xs text-primary-70">节点</label>
              <select
                value={selectedProvider}
                onChange={e => setSelectedProvider(e.target.value)}
                className="w-full bg-transparent border-b border-primary-50 focus:border-primary focus:outline-none py-2 pr-4 text-white font-sans transition-colors cursor-pointer appearance-none"
              >
                <option value="" className="bg-[#0a0a12]">默认代理集群</option>
                {providers.map(p => (
                  <option key={p.key} value={p.key} className="bg-[#0a0a12]">{p.name || p.key}</option>
                ))}
              </select>
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
              {candidates.map((cand, idx) => {
                const candId = String(cand.candidate_id || cand.tmdb_id || cand.id);
                const isPreviewLoading = previewingId === candId;
                return (
                  <div key={idx} className="border border-primary-30 bg-black/60 p-4 hover:border-primary-70 hover:bg-primary-10 transition-colors flex gap-4 group">
                    <div className="w-16 h-24 bg-primary-20 flex-shrink-0 flex items-center justify-center overflow-hidden border border-primary-30">
                      {resolveCandidatePoster(cand) ? (
                        <img
                          src={resolveCandidatePoster(cand)!}
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
                          <h4 className="font-bold text-white text-lg font-sans truncate hover:text-primary transition-colors">
                            {cand.source_url ? (
                              <a href={cand.source_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>
                                {cand.title || cand.name}
                              </a>
                            ) : (cand.title || cand.name)}
                          </h4>
                          <span className="text-xs text-primary-50 px-2 py-0.5 border border-primary-50 bg-primary-10 whitespace-nowrap">
                            {cand.provider_name || cand.provider || 'NeuralNode'}: {cand.external_id || cand.candidate_id || cand.tmdb_id || cand.id}
                          </span>
                        </div>
                        <div className="text-sm text-primary-70 font-sans mt-1">
                          年份: <span className="text-primary">{cand.year ? cand.year : (cand.release_date ? cand.release_date.substring(0,4) : (cand.first_air_date ? cand.first_air_date.substring(0,4) : '未知'))}</span> |
                          类型: <span className="text-primary">{cand.media_type === 'tv' || cand.subject_type === 2 ? '剧集/动漫' : '电影'}</span> |
                          原名: <span className="text-primary-50 truncate">{cand.original_title || cand.original_name || '-'}</span>
                          {cand.episode_count ? <span className="ml-2">| 集数: <span className="text-primary">{cand.episode_count}</span></span> : null}
                        </div>
                        <p className="text-xs text-primary-50 mt-2 line-clamp-2 font-sans leading-relaxed">{cand.overview}</p>
                      </div>
                    </div>
                    <div className="flex items-center justify-center ml-4">
                      <button
                        onClick={() => handlePreview(cand, candId, cand.provider || 'tmdb', cand.media_type)}
                        disabled={isPreviewLoading}
                        className="border border-primary text-primary px-4 py-2 hover:bg-primary hover:text-black font-bold flex items-center gap-2 transition-colors disabled:opacity-50 min-w-[120px] justify-center"
                      >
                        {isPreviewLoading ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                        {isPreviewLoading ? '预览中' : '预览差异'}
                      </button>
                    </div>
                  </div>
                );
              })}
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
