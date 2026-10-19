import React, { useEffect, useMemo, useState } from 'react';
import { X, Search, Loader2, Check } from 'lucide-react';
import { Movie } from '../types';
import { movieService } from '../api';

/**
 * 通用影片选择弹窗。两种使用方式：
 *   - mode="single"：选一部，confirm 时 onPick 收 string（影片 id）
 *   - mode="multi"：选多部，confirm 时 onPick 收 string[]
 *
 * 提供顶部搜索框 + 网格预览，搜索为防抖 350ms。空 query 时拉一组最新影片当
 * "热门候选"，让用户不用搜也能直接挑。
 */
interface BaseProps {
  open: boolean;
  title: string;
  onClose: () => void;
  /** 已选中的 id（用于回显勾选态）。 */
  initialSelected?: string[];
}

interface SingleProps extends BaseProps {
  mode: 'single';
  onPick: (id: string, movie: Movie) => void;
}

interface MultiProps extends BaseProps {
  mode: 'multi';
  onPick: (ids: string[], movies: Movie[]) => void;
}

export const MoviePickerModal: React.FC<SingleProps | MultiProps> = (props) => {
  const { open, title, onClose, initialSelected = [] } = props;
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [items, setItems] = useState<Movie[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelected));

  // 重新打开弹窗时把选中状态同步到传入的 initialSelected——上层切换 sectionId 时重用同一个组件。
  useEffect(() => {
    if (open) {
      setSelected(new Set(initialSelected));
      setQuery('');
      setDebounced('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 搜索防抖，避免每个按键都打后端
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  // 触发搜索
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    const run = async () => {
      try {
        let result: Movie[] = [];
        if (debounced) {
          result = await movieService.search(debounced);
        } else {
          // 空 query 时拉一批最新（按更新时间），让用户即开即选
          const r = await movieService.getAll(30, 1, { sort_by: 'update_time' });
          result = r?.items || [];
        }
        if (!alive) return;
        setItems(result || []);
      } catch (e) {
        if (!alive) return;
        setItems([]);
      } finally {
        if (alive) setLoading(false);
      }
    };
    run();
    return () => { alive = false; };
  }, [debounced, open]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (props.mode === 'single') {
        next.clear();
        next.add(id);
      } else {
        if (next.has(id)) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    const ids = Array.from(selected);
    if (props.mode === 'single') {
      const id = ids[0];
      const movie = items.find((m) => String(m.id) === id);
      if (id && movie) props.onPick(id, movie);
    } else {
      const movies = ids.map((id) => items.find((m) => String(m.id) === id)).filter(Boolean) as Movie[];
      props.onPick(ids, movies);
    }
    onClose();
  };

  const canConfirm = useMemo(() => {
    if (props.mode === 'single') return selected.size === 1;
    return true; // 多选可以保存空数组（清空 movie_ids）
  }, [selected, props.mode]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6" onClick={onClose}>
      <div
        className="w-full max-w-4xl max-h-[80vh] bg-[#0a0a12] border border-white/10 rounded-lg shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h3 className="text-lg font-['Orbitron'] font-bold text-white">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-3 border-b border-white/10">
          <div className="flex items-center gap-3 bg-black/40 border border-white/10 px-3 py-2 rounded">
            <Search size={16} className="text-gray-400" />
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索影片标题（留空显示最新影片）"
              className="flex-1 bg-transparent text-sm text-white outline-none"
            />
            {loading && <Loader2 size={14} className="text-gray-400 animate-spin" />}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {items.length === 0 && !loading ? (
            <div className="text-center text-gray-500 text-sm py-12">
              {debounced ? `没找到匹配 "${debounced}" 的影片` : '没有可选影片'}
            </div>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
              {items.map((m) => {
                const id = String(m.id);
                const checked = selected.has(id);
                return (
                  <button
                    key={id}
                    onClick={() => toggle(id)}
                    className={`relative aspect-[2/3] border overflow-hidden rounded-sm group transition-all ${
                      checked
                        ? 'border-primary shadow-[0_0_12px_var(--color-primary)]'
                        : 'border-white/10 hover:border-white/40'
                    }`}
                  >
                    {m.cover_url ? (
                      <img
                        src={m.cover_url}
                        alt={m.title}
                        referrerPolicy="no-referrer"
                        className="absolute inset-0 w-full h-full object-cover"
                      />
                    ) : (
                      <div className="absolute inset-0 bg-gray-900 flex items-center justify-center text-xs text-gray-500 px-2 text-center">
                        {m.title}
                      </div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 to-transparent p-2 text-left">
                      <div className="text-xs text-white truncate">{m.title}</div>
                      <div className="text-[10px] text-gray-400">{m.year}</div>
                    </div>
                    {checked && (
                      <div className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-primary flex items-center justify-center text-black">
                        <Check size={12} />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-3 border-t border-white/10">
          <div className="text-xs text-gray-400">
            {props.mode === 'multi'
              ? `已选 ${selected.size} 部`
              : selected.size === 1
              ? '已选 1 部'
              : '请选择 1 部影片'}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleConfirm}
              disabled={!canConfirm}
              className="px-5 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              确认
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
