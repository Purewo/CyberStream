// 聚合搜索 UI（本地测试专用，不上 GitHub）。
//
// 挂载位置：SearchResults.tsx 在本地库搜索结果为空时渲染本组件。
//
// 触发规则（严格遵守 skill 反爬约束）：
//   - 挂载即自动搜【默认源】（rarbt），且只搜这一个。
//   - 其他源做成 tab，用户【手动点击】才搜那个源；每源结果缓存，切回不重搜。
//   - 绝不一次性并发打所有源。
//
// 展示（仿本地影片卡片）：
//   - 列表用海报网格卡片，去掉播放相关信息。search 结果无海报 → 占位；
//     海报/磁力/网盘等详细数据【懒加载】，点卡片进详情视图才拉 detail。
//
// 仅 PC 端有本地桥（pc/aggregator/bridge.py，端口 10700）。桥没起时给提示。

import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Loader2, Magnet, Cloud, Copy, RefreshCw, Search, ChevronLeft, Star,
} from 'lucide-react';
import {
  aggregatorApi, AGG_SOURCES, DEFAULT_AGG_SOURCE,
  type AggSearchItem, type AggDetail,
} from './aggregatorApi';
import { toast } from '../../utils';
import { writeClipboard } from '../../platform';

type SourceState = {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'empty';
  items: AggSearchItem[];
  error?: string;
};

const emptyState: SourceState = { status: 'idle', items: [] };

// ── 海报占位（无图时仿 MovieCard 的首字母渐变） ──
const PosterFallback: React.FC<{ title: string }> = ({ title }) => (
  <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-[#1a1a20] to-black">
    <div className="text-6xl font-black text-white/10 font-['Orbitron']">{title?.charAt(0) || 'M'}</div>
  </div>
);

// ── 聚合结果卡片（仿 MovieCard，去掉 PLAY / tech badge / 播放信息） ──
const AggCard: React.FC<{ item: AggSearchItem; onOpen: (i: AggSearchItem) => void }> = ({ item, onOpen }) => {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={() => onOpen(item)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`relative flex-shrink-0 w-full max-w-[220px] mx-auto aspect-[2/3] transition-all duration-300 ease-out cursor-pointer group ${hovered ? 'scale-105 z-20' : 'scale-100 z-10'}`}
    >
      <div className={`h-full w-full bg-[#0a0a12] border border-white/10 relative overflow-hidden ${hovered ? 'border-primary shadow-[0_0_15px_var(--color-primary)]' : ''}`}>
        <PosterFallback title={item.title} />
        {/* 底部信息浮层：只放片名 + 来源年份，无播放按钮 */}
        <div className={`absolute inset-0 bg-black/85 flex flex-col justify-end p-3 transition-opacity duration-300 ${hovered ? 'opacity-100' : 'opacity-0'}`}>
          <h3 className="text-primary font-['Orbitron'] text-xs font-bold line-clamp-3">{item.title}</h3>
          {(item.years || item.category) && (
            <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-300 font-['Rajdhani']">
              {item.years && <span>{item.years}</span>}
              {item.category && <span className="text-secondary">{item.category}</span>}
            </div>
          )}
          <div className="mt-2 text-[10px] text-gray-400 font-['Rajdhani'] tracking-wider">查看资源 →</div>
        </div>
        {/* 常态底部片名条（未 hover 也能看清是什么片） */}
        <div className={`absolute bottom-0 inset-x-0 p-2 bg-gradient-to-t from-black/90 to-transparent transition-opacity ${hovered ? 'opacity-0' : 'opacity-100'}`}>
          <h3 className="text-white/90 font-['Noto_Sans_SC'] text-xs font-bold line-clamp-2">{item.title}</h3>
        </div>
      </div>
    </div>
  );
};

// ── 聚合详情视图（仿 MovieDetail：左海报 + 右元数据 + 资源列表） ──
const AggDetailView: React.FC<{
  item: AggSearchItem;
  source: string;
  onBack: () => void;
}> = ({ item, source, onBack }) => {
  const [detail, setDetail] = useState<AggDetail | null | 'loading' | 'error'>('loading');

  useEffect(() => {
    let cancelled = false;
    setDetail('loading');
    (async () => {
      try {
        const d = await aggregatorApi.detail(item.link, source);
        if (!cancelled) setDetail(d || 'error');
      } catch {
        if (!cancelled) setDetail('error');
      }
    })();
    return () => { cancelled = true; };
  }, [item.link, source]);

  const copy = async (text: string, label: string) => {
    try { await writeClipboard(text); toast.success(`${label}已复制`); }
    catch { toast.error('复制失败'); }
  };

  const asText = (v: string | string[] | undefined): string =>
    Array.isArray(v) ? v.filter(Boolean).join(' / ') : (v || '');

  const d = detail !== 'loading' && detail !== 'error' && detail ? detail : null;
  const poster = d?.poster;

  return (
    <div className="animate-in fade-in duration-200">
      <button onClick={onBack} className="group flex items-center gap-2 text-gray-400 hover:text-primary mb-6 transition-colors">
        <ChevronLeft className="group-hover:-translate-x-1 transition-transform" size={20} />
        <span className="font-['Rajdhani'] font-bold tracking-wider">返回结果</span>
      </button>

      <div className="flex flex-col md:flex-row gap-6 md:gap-10">
        {/* 左：海报 */}
        <div className="w-full sm:w-[260px] md:w-[300px] flex-shrink-0">
          <div className="aspect-[2/3] w-full bg-[#0a0a12] border border-white/10 relative overflow-hidden rounded-sm shadow-2xl">
            {poster ? (
              <img src={poster} alt={item.title} referrerPolicy="no-referrer" className="absolute inset-0 w-full h-full object-cover" />
            ) : (
              <PosterFallback title={item.title} />
            )}
          </div>
          {(d?.douban_score || d?.imdb_score) && (
            <div className="flex items-center gap-4 mt-3 text-sm font-['Rajdhani']">
              {d?.douban_score && d.douban_score !== 'N/A' && (
                <span className="flex items-center gap-1 text-secondary"><Star size={13} fill="currentColor" /> 豆瓣 {d.douban_score}</span>
              )}
              {d?.imdb_score && d.imdb_score !== 'N/A' && (
                <span className="text-amber-400">IMDb {d.imdb_score}</span>
              )}
            </div>
          )}
        </div>

        {/* 右：元数据 + 资源 */}
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl md:text-3xl font-['Noto_Sans_SC'] font-bold text-white mb-3">{item.title}</h1>

          {detail === 'loading' && (
            <div className="flex items-center gap-2 text-gray-400 py-8">
              <Loader2 size={18} className="animate-spin" /><span className="font-['Rajdhani']">加载详情…</span>
            </div>
          )}
          {detail === 'error' && (
            <div className="text-red-300 text-sm py-6">详情解析失败。<button onClick={onBack} className="underline">返回</button>重试。</div>
          )}

          {d && (
            <>
              {/* 元数据 */}
              <div className="space-y-1.5 text-sm text-gray-300 font-['Noto_Sans_SC'] mb-6">
                {asText(d.director) && <p><span className="text-gray-500">导演：</span>{asText(d.director)}</p>}
                {asText(d.actors) && <p className="line-clamp-2"><span className="text-gray-500">主演：</span>{asText(d.actors)}</p>}
                {asText(d.description) && (
                  <p className="text-gray-400 leading-relaxed line-clamp-4 pt-2 border-t border-white/5 mt-2">{asText(d.description)}</p>
                )}
              </div>

              {/* 网盘链接 */}
              {d.cloud_links && d.cloud_links.length > 0 && (
                <div className="mb-6">
                  <h3 className="text-xs font-['Orbitron'] tracking-widest text-cyan-400 mb-2">网盘链接 · CLOUD</h3>
                  <div className="space-y-1.5">
                    {d.cloud_links.map((cl, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs bg-black/30 border border-white/10 rounded p-2">
                        <Cloud size={13} className="text-cyan-400 shrink-0" />
                        <span className="text-gray-400 shrink-0">{cl.provider || '网盘'}</span>
                        <a href={cl.url} target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline truncate flex-1">{cl.url}</a>
                        {cl.password && <span className="text-gray-500 shrink-0">码:{cl.password}</span>}
                        <button onClick={() => copy(cl.url + (cl.password ? ` 提取码:${cl.password}` : ''), '网盘链接')} className="shrink-0 text-gray-500 hover:text-primary"><Copy size={12} /></button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 磁力分组 */}
              {d.file_content && d.file_content.length > 0 && (
                <div>
                  <h3 className="text-xs font-['Orbitron'] tracking-widest text-purple-400 mb-2">磁力资源 · MAGNET</h3>
                  <div className="space-y-3">
                    {d.file_content.map((g, gi) => (
                      <div key={gi}>
                        <div className="text-[11px] text-primary/70 font-['Orbitron'] tracking-wider mb-1">
                          {g.quality} {g.number ? `· ${g.number}` : ''}
                        </div>
                        <div className="space-y-1">
                          {(g.file_list || []).map((f, fi) => (
                            <div key={fi} className="flex items-center gap-2 text-xs bg-black/20 rounded px-2 py-1.5 hover:bg-white/5">
                              <Magnet size={12} className="text-purple-400 shrink-0" />
                              <span className="text-gray-300 truncate flex-1" title={f.file_name}>{f.file_name.replace(/^复制/, '')}</span>
                              {f.file_size && <span className="text-gray-500 shrink-0">{f.file_size}</span>}
                              <button onClick={() => copy(f.final_link, '链接')} className="shrink-0 text-gray-500 hover:text-primary"><Copy size={12} /></button>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {(!d.cloud_links?.length && !d.file_content?.length) && (
                <p className="text-sm text-gray-500 py-4">该条目暂无可提取的资源链接</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export const AggregateSearch: React.FC<{ query: string }> = ({ query }) => {
  const [available, setAvailable] = useState<boolean | null>(null); // null=探测中
  const [activeSource, setActiveSource] = useState<string>(DEFAULT_AGG_SOURCE);
  const [bySource, setBySource] = useState<Record<string, SourceState>>({});
  const [opened, setOpened] = useState<AggSearchItem | null>(null); // 当前打开的详情条目
  const searchedRef = useRef<Set<string>>(new Set());

  const runSearch = useCallback(async (source: string) => {
    if (searchedRef.current.has(source)) return;
    searchedRef.current.add(source);
    setBySource((prev) => ({ ...prev, [source]: { status: 'loading', items: [] } }));
    try {
      const items = await aggregatorApi.search(query, source);
      setBySource((prev) => ({ ...prev, [source]: { status: items.length ? 'ready' : 'empty', items } }));
    } catch (e: any) {
      setBySource((prev) => ({ ...prev, [source]: { status: 'error', items: [], error: e?.message || '请求失败' } }));
    }
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    searchedRef.current = new Set();
    setBySource({});
    setOpened(null);
    setActiveSource(DEFAULT_AGG_SOURCE);
    (async () => {
      const ok = await aggregatorApi.isAvailable();
      if (cancelled) return;
      setAvailable(ok);
      if (ok) runSearch(DEFAULT_AGG_SOURCE);
    })();
    return () => { cancelled = true; };
  }, [query, runSearch]);

  const handlePickSource = (source: string) => {
    setOpened(null);
    setActiveSource(source);
    runSearch(source);
  };

  const handleManualRetry = (source: string) => {
    searchedRef.current.delete(source);
    runSearch(source);
  };

  const cur = bySource[activeSource] || emptyState;

  return (
    <div className="mt-10 max-w-6xl mx-auto">
      <div className="flex items-center gap-2 mb-4">
        <Search size={16} className="text-primary" />
        <h2 className="font-['Orbitron'] text-sm tracking-widest text-primary">聚合搜索 · 外部资源站</h2>
        {available === null && <Loader2 size={14} className="animate-spin text-gray-500" />}
      </div>

      {/* 源 tab（详情视图时也保留，方便切源） */}
      <div className="flex flex-wrap gap-2 mb-6">
        {AGG_SOURCES.map((s) => {
          const st = bySource[s.name]?.status;
          const active = s.name === activeSource;
          return (
            <button key={s.name} onClick={() => handlePickSource(s.name)}
              className={`px-3 py-1.5 rounded-full text-xs font-['Rajdhani'] font-bold border transition-all flex items-center gap-1.5 ${active ? 'bg-primary/20 text-primary border-primary shadow-[0_0_10px_rgba(0,243,255,0.25)]' : 'bg-black/40 text-gray-400 border-white/10 hover:border-primary/50 hover:text-primary'}`}>
              {s.label}
              {st === 'loading' && <Loader2 size={11} className="animate-spin" />}
              {s.isDefault && <span className="text-[9px] opacity-60">自动</span>}
            </button>
          );
        })}
      </div>

      {/* 详情视图 vs 网格视图 */}
      {opened ? (
        <AggDetailView item={opened} source={activeSource} onBack={() => setOpened(null)} />
      ) : (
        <>
          {cur.status === 'loading' && (
            <div className="flex items-center gap-2 text-gray-400 py-12 justify-center">
              <Loader2 size={18} className="animate-spin" /><span className="font-['Rajdhani']">正在搜索 {activeSource}…</span>
            </div>
          )}
          {cur.status === 'error' && (
            <div className="flex items-center justify-between gap-3 border border-red-500/30 bg-red-500/5 rounded-lg p-4">
              <span className="text-sm text-red-300">搜索失败：{cur.error}</span>
              <button onClick={() => handleManualRetry(activeSource)} className="shrink-0 px-3 py-1.5 text-xs font-bold rounded border border-red-400/50 text-red-300 hover:bg-red-500/10 flex items-center gap-1">
                <RefreshCw size={12} /> 重试
              </button>
            </div>
          )}
          {cur.status === 'empty' && (
            <div className="text-center py-12 text-gray-500 font-['Rajdhani']">该源未找到「{query}」，可换上方其他源试试</div>
          )}
          {cur.status === 'ready' && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4 md:gap-6 justify-center">
              {cur.items.map((item) => (
                <AggCard key={item.link} item={item} onOpen={setOpened} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};
