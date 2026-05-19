import React, { useState, useEffect } from "react";
import { Loader2, Plus, Link as LinkIcon, Search, AlertCircle, X, Check, Sparkles } from "lucide-react";
import { movieService, libraryService } from "../api";
import { toast } from "../utils";
import { Library as LibraryType, Movie } from "../types";
import { TMDBMatchModal } from "./TMDBMatchModal";

interface CreateManualModalProps {
  resourceId: string;
  defaultTitle: string;
  onClose: () => void;
  onCreated: () => void;
}

const CreateManualModal: React.FC<CreateManualModalProps> = ({ resourceId, defaultTitle, onClose, onCreated }) => {
  const [title, setTitle] = useState(defaultTitle);
  const [mediaType, setMediaType] = useState<"movie" | "tv">("movie");
  const [overview, setOverview] = useState("");
  const [libraries, setLibraries] = useState<LibraryType[]>([]);
  const [selectedLibraryIds, setSelectedLibraryIds] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    libraryService.getLibraries().then(setLibraries).catch(console.error);
  }, []);

  const toggleLibrary = (id: number) => {
    setSelectedLibraryIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const handleSubmit = async () => {
    if (!title.trim()) {
      toast.error("请填写标题");
      return;
    }
    setSubmitting(true);
    try {
      const result = await movieService.createManualMovie({
        title: title.trim(),
        media_type: mediaType,
        overview: overview.trim() || undefined,
        resource_ids: [resourceId],
        library_ids: selectedLibraryIds.length > 0 ? selectedLibraryIds : undefined,
        preserve_episode_metadata: false,
      });
      if (result) {
        toast.success(`手工条目《${title.trim()}》已创建`);
        onCreated();
        onClose();
      } else {
        toast.error("创建失败，请检查后端日志");
      }
    } catch (e: any) {
      toast.error(e?.message || "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#0a0a12] border border-primary-30 w-full max-w-md flex flex-col font-mono text-cyan-50 shadow-[0_0_30px_rgba(6,182,212,0.15)] max-h-[90vh]">
        <div className="p-4 border-b border-primary-30 flex justify-between items-center bg-primary-10 shrink-0">
          <div className="flex items-center gap-2 text-primary">
            <Plus size={20} />
            <h3 className="font-bold tracking-widest text-lg">创建手工条目</h3>
          </div>
          <button onClick={onClose} className="text-primary-50 hover:text-white hover:bg-red-500/80 p-1 transition-colors rounded">
            <X size={24} />
          </button>
        </div>

        <div className="p-6 space-y-4 overflow-y-auto">
          <div>
            <label className="text-xs text-primary-50 uppercase tracking-widest block mb-2">标题 *</label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="w-full bg-black/50 border border-primary-30 focus:border-primary focus:outline-none p-2 text-cyan-50 font-sans"
            />
          </div>

          <div>
            <label className="text-xs text-primary-50 uppercase tracking-widest block mb-2">媒体类型</label>
            <div className="flex gap-2">
              {(["movie", "tv"] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setMediaType(t)}
                  className={`flex-1 px-3 py-2 text-xs uppercase tracking-widest border transition-colors ${mediaType === t ? "bg-primary text-black border-primary" : "border-primary-30 text-primary-50 hover:border-primary"}`}
                >
                  {t === "movie" ? "电影" : "剧集"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-primary-50 uppercase tracking-widest block mb-2">简介（可选）</label>
            <textarea
              value={overview}
              onChange={e => setOverview(e.target.value)}
              rows={3}
              className="w-full bg-black/50 border border-primary-30 focus:border-primary focus:outline-none p-2 text-cyan-50 font-sans resize-none"
            />
          </div>

          <div>
            <label className="text-xs text-primary-50 uppercase tracking-widest block mb-2">挂入片库（可选，可多选）</label>
            {libraries.length === 0 ? (
              <p className="text-xs text-primary-50">暂无片库</p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {libraries.map(lib => (
                  <label key={lib.id} className="flex items-center gap-2 p-2 hover:bg-primary-5 cursor-pointer text-sm">
                    <input
                      type="checkbox"
                      checked={selectedLibraryIds.includes(lib.id)}
                      onChange={() => toggleLibrary(lib.id)}
                      className="accent-primary"
                    />
                    <span>{lib.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t border-primary-30 bg-black/40 flex justify-end gap-3 shrink-0">
          <button onClick={onClose} className="px-4 py-2 border border-primary-30 text-primary-50 hover:text-primary hover:bg-primary-10 transition-colors text-sm uppercase tracking-widest">
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-6 py-2 bg-primary text-black font-bold flex items-center gap-2 hover:bg-primary-hover transition-colors disabled:opacity-50 uppercase tracking-widest"
          >
            {submitting && <Loader2 className="animate-spin w-4 h-4" />}
            创建
          </button>
        </div>
      </div>
    </div>
  );
};

interface AttachToExistingModalProps {
  resourceId: string;
  defaultQuery: string;
  onClose: () => void;
  onAttached: () => void;
}

const AttachToExistingModal: React.FC<AttachToExistingModalProps> = ({ resourceId, defaultQuery, onClose, onAttached }) => {
  const [query, setQuery] = useState(defaultQuery);
  const [results, setResults] = useState<Movie[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedMovie, setSelectedMovie] = useState<Movie | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const data = await movieService.search(query.trim());
      setResults(data);
    } catch (e) {
      console.error(e);
      toast.error("搜索失败");
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    if (defaultQuery) runSearch();
  }, []);

  const handleSubmit = async () => {
    if (!selectedMovie) {
      toast.error("请先选择目标影片");
      return;
    }
    setSubmitting(true);
    try {
      const result = await movieService.attachResourceToMovie(String(selectedMovie.id), {
        resource_ids: [resourceId],
        preserve_episode_metadata: false,
      });
      if (result) {
        toast.success(`资源已挂载到《${selectedMovie.title}》`);
        onAttached();
        onClose();
      } else {
        toast.error("挂载失败");
      }
    } catch (e: any) {
      toast.error(e?.message || "挂载失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#0a0a12] border border-primary-30 w-full max-w-lg flex flex-col font-mono text-cyan-50 shadow-[0_0_30px_rgba(6,182,212,0.15)] max-h-[90vh]">
        <div className="p-4 border-b border-primary-30 flex justify-between items-center bg-primary-10 shrink-0">
          <div className="flex items-center gap-2 text-primary">
            <LinkIcon size={20} />
            <h3 className="font-bold tracking-widest text-lg">挂载到现有影视</h3>
          </div>
          <button onClick={onClose} className="text-primary-50 hover:text-white hover:bg-red-500/80 p-1 transition-colors rounded">
            <X size={24} />
          </button>
        </div>

        <div className="p-6 space-y-4 overflow-y-auto flex-1 min-h-0 flex flex-col">
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") runSearch(); }}
              placeholder="输入影片标题搜索..."
              className="flex-1 bg-black/50 border border-primary-30 focus:border-primary focus:outline-none p-2 text-cyan-50 font-sans"
            />
            <button
              onClick={runSearch}
              disabled={searching}
              className="px-4 py-2 border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-50"
            >
              {searching ? <Loader2 className="animate-spin w-4 h-4" /> : <Search className="w-4 h-4" />}
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 min-h-[200px]">
            {searching ? (
              <div className="flex items-center justify-center py-8 text-primary-50">
                <Loader2 className="animate-spin w-6 h-6" />
              </div>
            ) : results.length === 0 ? (
              <div className="text-center py-8 text-primary-50 text-sm">
                {query ? "无匹配结果" : "输入关键字开始搜索"}
              </div>
            ) : (
              results.map(m => (
                <button
                  key={m.id}
                  onClick={() => setSelectedMovie(m)}
                  className={`w-full flex items-center gap-3 p-2 text-left border transition-colors ${selectedMovie?.id === m.id ? "border-primary bg-primary-10" : "border-primary-30/30 hover:border-primary-30"}`}
                >
                  {selectedMovie?.id === m.id && <Check className="w-4 h-4 text-primary shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white truncate">{m.title}</div>
                    <div className="text-xs text-primary-50">{m.year || "—"} · {m.type || "—"}</div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="p-4 border-t border-primary-30 bg-black/40 flex justify-end gap-3 shrink-0">
          <button onClick={onClose} className="px-4 py-2 border border-primary-30 text-primary-50 hover:text-primary hover:bg-primary-10 transition-colors text-sm uppercase tracking-widest">
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !selectedMovie}
            className="px-6 py-2 bg-primary text-black font-bold flex items-center gap-2 hover:bg-primary-hover transition-colors disabled:opacity-50 uppercase tracking-widest"
          >
            {submitting && <Loader2 className="animate-spin w-4 h-4" />}
            确认挂载
          </button>
        </div>
      </div>
    </div>
  );
};

export const OtherVideosArchive = () => {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pagination, setPagination] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");

  const [createModalItem, setCreateModalItem] = useState<any>(null);
  const [attachModalItem, setAttachModalItem] = useState<any>(null);
  const [matchModalItem, setMatchModalItem] = useState<any>(null);

  const fetchItems = async (p = 1, kw = appliedKeyword) => {
    setLoading(true);
    setError("");
    try {
      const res = await movieService.listOtherVideos(p, 20, kw ? { keyword: kw } : undefined);
      setItems(res.items || []);
      setPagination(res.meta);
      setPage(p);
    } catch (e: any) {
      setError(e.message || "获取其他视频归档失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems(1, appliedKeyword);
  }, [appliedKeyword]);

  const handleSearch = () => {
    setAppliedKeyword(keyword.trim());
  };

  return (
    <div className="bg-[#0a0a0a] border border-primary-30 text-gray-200">
      <div className="p-4 border-b border-primary-30 flex items-center justify-between bg-primary-5">
        <h2 className="text-lg font-bold text-primary tracking-widest uppercase flex items-center gap-2">
          <span className="w-2 h-4 bg-primary inline-block"></span>
          其他视频归档池
        </h2>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") handleSearch(); }}
              placeholder="搜索视频..."
              className="bg-black/40 border border-primary-30 text-white pl-9 pr-4 py-1.5 text-sm focus:border-primary focus:outline-none transition-colors"
            />
          </div>
        </div>
      </div>

      <div className="p-4">
        {error && (
          <div className="mb-4 p-3 bg-red-900/40 border border-red-500/50 text-red-200 text-sm flex items-start gap-3">
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 text-primary-50">
            <Loader2 className="animate-spin w-8 h-8 mb-4" />
            <span className="tracking-widest capitalize text-sm">正在扫描深层数据链路...</span>
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-20 text-gray-500 text-sm font-mono tracking-wider">
            没有发现未归档的其他视频。
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-white/10 text-primary-50">
                  <th className="p-3 font-normal tracking-wide uppercase">视频源标识</th>
                  <th className="p-3 font-normal tracking-wide uppercase">识别结果 / 标题</th>
                  <th className="p-3 font-normal tracking-wide uppercase">元数据状态</th>
                  <th className="p-3 font-normal tracking-wide uppercase text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => {
                  const recommendation = item.recommended_resolution || 'create_manual_movie';
                  const matchPreferred = recommendation === 'match_metadata';
                  const matchAvailable = !!item.actions?.match_metadata && !!item.movie_id;
                  return (
                  <tr key={item.resource_id || index} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                    <td className="p-3 align-top">
                      <div className="font-medium text-gray-300 break-all leading-relaxed">
                        {item.resource_info?.file?.filename || "未知文件"}
                      </div>
                      <div className="text-xs text-gray-500 mt-1 break-all">
                        {item.resource_info?.file?.relative_path || item.resource_id}
                      </div>
                    </td>
                    <td className="p-3 align-top text-gray-400">
                      <div className="flex flex-col gap-1">
                        <span>
                          {item.movie_title || "-"}
                          {item.movie_year && <span className="ml-2 text-xs opacity-60">({item.movie_year})</span>}
                        </span>
                        {matchPreferred && (
                          <span className="inline-flex items-center gap-1 text-[10px] text-primary uppercase tracking-wider">
                            <Sparkles className="w-3 h-3" /> 后端建议匹配元数据
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="p-3 align-top">
                      <span className={`inline-block px-2 py-0.5 text-xs border ${
                        item.metadata_state?.is_locked
                          ? 'bg-blue-900/30 text-blue-400 border-blue-500/30'
                          : 'bg-primary-10 text-primary border-primary-30'
                      }`}>
                        {item.metadata_state?.source_group || "UNKNOWN"}
                      </span>
                    </td>
                    <td className="p-3 align-top text-right whitespace-nowrap">
                      <div className="flex justify-end gap-2">
                        {matchAvailable && (
                          <button
                            onClick={() => setMatchModalItem(item)}
                            className={`px-3 py-1 transition-colors flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider ${
                              matchPreferred
                                ? 'bg-primary text-black hover:bg-primary-70'
                                : 'bg-transparent border border-primary text-primary hover:bg-primary hover:text-black'
                            }`}
                          >
                            <Search className="w-3.5 h-3.5" />
                            匹配影视元数据
                          </button>
                        )}
                        <button
                          onClick={() => setCreateModalItem(item)}
                          className={`px-3 py-1 transition-colors flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider ${
                            !matchPreferred
                              ? 'bg-primary text-black hover:bg-primary-70'
                              : 'bg-transparent border border-white/20 text-gray-300 hover:border-primary hover:text-primary'
                          }`}
                        >
                          <Plus className="w-3.5 h-3.5" />
                          创建手工条目
                        </button>
                        <button
                          onClick={() => setAttachModalItem(item)}
                          className="px-3 py-1 bg-transparent border border-white/20 text-gray-300 hover:border-primary hover:text-primary transition-colors flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider"
                        >
                          <LinkIcon className="w-3.5 h-3.5" />
                          挂载到现有影视
                        </button>
                      </div>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {pagination && pagination.total_pages > 1 && (
          <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-4">
            <span className="text-primary-50 tracking-widest text-sm flex items-center gap-4">
              当前页 {pagination.current_page} / 总页数 {pagination.total_pages} (共 {pagination.total_items} 项)
              <span className="flex items-center gap-2">
                  前往 <input
                      type="number"
                      min={1}
                      max={pagination.total_pages || 1}
                      className="w-16 bg-black/40 border border-primary-30 text-primary text-center py-1 focus:border-primary focus:outline-none transition-colors"
                      onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                              const p = parseInt(e.currentTarget.value);
                              if(p > 0 && p <= pagination.total_pages) fetchItems(p);
                          }
                      }}
                      placeholder={String(page)}
                  /> 页
              </span>
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => fetchItems(page - 1)}
                disabled={page <= 1}
                className="px-4 py-1.5 border border-primary-30 text-primary hover:bg-primary-10 disabled:opacity-30 disabled:hover:bg-transparent transition-colors text-sm"
              >
                上一页
              </button>
              <button
                onClick={() => fetchItems(page + 1)}
                disabled={page >= pagination.total_pages}
                className="px-4 py-1.5 border border-primary-30 text-primary hover:bg-primary-10 disabled:opacity-30 disabled:hover:bg-transparent transition-colors text-sm"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>

      {createModalItem && (
        <CreateManualModal
          resourceId={createModalItem.resource_id}
          defaultTitle={createModalItem.resource_info?.file?.filename?.replace(/\.[^.]+$/, "") || ""}
          onClose={() => setCreateModalItem(null)}
          onCreated={() => fetchItems(page, appliedKeyword)}
        />
      )}
      {attachModalItem && (
        <AttachToExistingModal
          resourceId={attachModalItem.resource_id}
          defaultQuery={attachModalItem.resource_info?.file?.filename?.replace(/\.[^.]+$/, "") || ""}
          onClose={() => setAttachModalItem(null)}
          onAttached={() => fetchItems(page, appliedKeyword)}
        />
      )}
      {matchModalItem && matchModalItem.movie_id && (
        <TMDBMatchModal
          movieId={matchModalItem.movie_id}
          initialQuery={
            matchModalItem.actions?.match_metadata?.search?.params?.query
              || matchModalItem.metadata_match_context?.suggested_query
              || matchModalItem.movie_title
              || ''
          }
          initialYear={
            matchModalItem.actions?.match_metadata?.search?.params?.year
              ?? matchModalItem.metadata_match_context?.suggested_year
              ?? matchModalItem.movie_year
          }
          onClose={() => setMatchModalItem(null)}
          onMatch={() => {
            setMatchModalItem(null);
            toast.success('元数据已应用，归档列表已更新');
            fetchItems(page, appliedKeyword);
            window.dispatchEvent(new CustomEvent('movie-updated'));
          }}
        />
      )}
    </div>
  );
};
