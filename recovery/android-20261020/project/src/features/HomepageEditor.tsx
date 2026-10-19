import React, { useEffect, useMemo, useState } from 'react';
import {
  GripVertical,
  Plus,
  Trash2,
  Save,
  Loader2,
  Pin,
  PinOff,
  Hash,
  Star,
} from 'lucide-react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { homeService, movieService } from '../api';
import { HomepageConfig, HomepageSectionConfig, Movie } from '../types';
import { toast } from '../utils';
import { MoviePickerModal } from './MoviePickerModal';

/**
 * 主页深度定制编辑器：钉首屏大海报 + 增删/排序/编辑首页分类区块。
 * 数据全部走服务端 /api/v1/homepage/config，影响所有访问者。
 */
export const HomepageEditor: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<HomepageConfig | null>(null);
  // 全局可选 genre 列表（用于 latest mode 选项）
  const [genres, setGenres] = useState<string[]>([]);
  // hero 影片对象缓存（拉到 hero_movie_id 后异步取完整 Movie 用于卡片渲染）
  const [heroMovie, setHeroMovie] = useState<Movie | null>(null);
  const [heroPickerOpen, setHeroPickerOpen] = useState(false);
  // 当前正在用 picker 编辑哪个 section 的 custom 影片列表
  const [customPickerForKey, setCustomPickerForKey] = useState<string | null>(null);
  // section 的 custom 影片对象缓存：sectionKey -> Movie[]，用于显示缩略图
  const [customCache, setCustomCache] = useState<Record<string, Movie[]>>({});
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  // 初次加载
  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      const [cfg, filters] = await Promise.all([
        homeService.getHomepageConfig(),
        movieService.getGlobalFilters(),
      ]);
      if (!alive) return;
      // 后端 sections 可能没有 sort_order，归一化一下：缺就按数组顺序补
      const normalized: HomepageConfig = cfg
        ? {
            ...cfg,
            sections: (cfg.sections || []).map((s, i) => ({
              ...s,
              sort_order: typeof s.sort_order === 'number' ? s.sort_order : i,
              limit: s.limit ?? 10,
              enabled: s.enabled ?? true,
              mode: s.mode ?? 'latest',
            })).sort((a, b) => a.sort_order - b.sort_order),
          }
        : { hero_movie_id: null, sections: [] };
      setConfig(normalized);
      // FilterDictionaries.genres 是 Genre[]（{name,slug,count}），UI 这里只要 name 字符串
      const genreNames: string[] = ((filters?.genres as any[]) || [])
        .map((g) => (typeof g === 'string' ? g : g?.name))
        .filter(Boolean);
      setGenres(genreNames);
      setLoading(false);
    })();
    return () => { alive = false; };
  }, []);

  // 拉 hero 影片对象（仅用于显示卡片，不影响保存）
  useEffect(() => {
    let alive = true;
    if (!config?.hero_movie_id) {
      setHeroMovie(null);
      return;
    }
    movieService.getDetail(config.hero_movie_id).then((m) => {
      if (alive) setHeroMovie(m);
    });
    return () => { alive = false; };
  }, [config?.hero_movie_id]);

  // 拉 custom mode 各 section 的影片对象
  useEffect(() => {
    if (!config) return;
    const ids = new Set<string>();
    for (const sec of config.sections) {
      if (sec.mode === 'custom') {
        (sec.movie_ids || []).forEach((id) => ids.add(id));
      }
    }
    // 已经缓存过的不重复请求
    const cachedMovies = (Object.values(customCache) as Movie[][]).flat();
    const cached = new Set(cachedMovies.map((m) => String(m.id)));
    const toFetch = Array.from(ids).filter((id) => !cached.has(id));
    if (toFetch.length === 0) return;
    let alive = true;
    Promise.all(toFetch.map((id) => movieService.getDetail(id))).then((movies) => {
      if (!alive) return;
      const flat = movies.filter(Boolean) as Movie[];
      const next: Record<string, Movie[]> = { ...customCache };
      for (const sec of config.sections) {
        if (sec.mode === 'custom') {
          next[sec.key] = (sec.movie_ids || [])
            .map((id) => flat.find((m) => String(m.id) === id) || customCache[sec.key]?.find((m) => String(m.id) === id))
            .filter(Boolean) as Movie[];
        }
      }
      setCustomCache(next);
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.sections]);

  const updateSection = (key: string, patch: Partial<HomepageSectionConfig>) => {
    setConfig((prev) => prev ? {
      ...prev,
      sections: prev.sections.map((s) => s.key === key ? { ...s, ...patch } : s),
    } : prev);
    setDirty(true);
  };

  const removeSection = (key: string) => {
    setConfig((prev) => prev ? {
      ...prev,
      sections: prev.sections.filter((s) => s.key !== key),
    } : prev);
    setDirty(true);
  };

  const addSection = () => {
    setConfig((prev) => {
      if (!prev) return prev;
      // 生成一个不冲突的新 key
      let i = 1;
      let key = `section_${i}`;
      while (prev.sections.some((s) => s.key === key)) { i++; key = `section_${i}`; }
      const fresh: HomepageSectionConfig = {
        key,
        title: '新分类',
        genre: genres[0] || '',
        mode: 'latest',
        limit: 10,
        movie_ids: [],
        enabled: true,
        sort_order: prev.sections.length,
      };
      return { ...prev, sections: [...prev.sections, fresh] };
    });
    setDirty(true);
  };

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setConfig((prev) => {
      if (!prev) return prev;
      const oldIndex = prev.sections.findIndex((s) => s.key === active.id);
      const newIndex = prev.sections.findIndex((s) => s.key === over.id);
      if (oldIndex < 0 || newIndex < 0) return prev;
      const moved = arrayMove<HomepageSectionConfig>(prev.sections, oldIndex, newIndex);
      return {
        ...prev,
        sections: moved.map((s, i) => ({ ...s, sort_order: i })),
      };
    });
    setDirty(true);
  };

  // hero 写入即保存（hero 是单值，没必要等"保存全部"）
  const pinHero = async (id: string | null) => {
    setSaving(true);
    const patched = await homeService.updateHomepageConfig({ hero_movie_id: id });
    setSaving(false);
    if (!patched) {
      toast.error('钉影片失败');
      return;
    }
    setConfig((prev) => prev ? { ...prev, hero_movie_id: id } : prev);
    // 通知首页失效缓存重新拉
    window.dispatchEvent(new CustomEvent('homepage-config-updated'));
    toast.success(id ? '首屏大海报已钉定' : '已取消钉定');
  };

  const saveAll = async () => {
    if (!config) return;
    // 校验：custom 模式必须有至少 1 部影片
    const invalid = config.sections.filter((s) => s.enabled && s.mode === 'custom' && (s.movie_ids?.length || 0) === 0);
    if (invalid.length > 0) {
      toast.error(`这些 custom 分类还没选影片：${invalid.map((s) => s.title).join('、')}`);
      return;
    }
    setSaving(true);
    const patched = await homeService.updateHomepageConfig({ sections: config.sections });
    setSaving(false);
    if (!patched) {
      toast.error('保存失败');
      return;
    }
    setDirty(false);
    // 通知首页失效缓存重新拉
    window.dispatchEvent(new CustomEvent('homepage-config-updated'));
    toast.success('首页配置已更新');
  };

  if (loading) {
    return (
      <div className="bg-[#0a0a12]/80 border border-white/10 p-12 flex items-center justify-center text-gray-400">
        <Loader2 size={20} className="animate-spin mr-2" /> 正在加载首页配置…
      </div>
    );
  }
  if (!config) {
    return (
      <div className="bg-[#0a0a12]/80 border border-white/10 p-6 text-red-400 text-sm">
        加载首页配置失败。请检查后端连通性后刷新页面。
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Hero 区 */}
      <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
        <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-2">
          <Pin size={18} /> 首屏大海报
        </h3>
        <p className="text-xs text-gray-500 mb-4 leading-relaxed">
          钉一部影片，所有访问者打开首页都会看见。设为空表示由后端自动推荐。
        </p>
        {heroMovie ? (
          <div className="flex gap-4 items-stretch">
            <div className="w-24 aspect-[2/3] flex-shrink-0 bg-gray-900 border border-white/10 overflow-hidden">
              {heroMovie.cover_url && (
                <img src={heroMovie.cover_url} alt={heroMovie.title} referrerPolicy="no-referrer" className="w-full h-full object-cover" />
              )}
            </div>
            <div className="flex-1 flex flex-col justify-between min-w-0">
              <div className="min-w-0">
                <div className="text-white font-bold truncate">{heroMovie.title}</div>
                <div className="text-xs text-gray-400 mt-1">
                  {heroMovie.year} {heroMovie.rating ? `· ★ ${heroMovie.rating}` : ''}
                </div>
                <div className="text-xs text-gray-500 mt-2 line-clamp-3">
                  {heroMovie.desc || heroMovie.overview || '—'}
                </div>
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => setHeroPickerOpen(true)}
                  className="px-3 py-1.5 text-xs border border-primary/50 text-primary hover:bg-primary hover:text-black transition-colors"
                >
                  更换
                </button>
                <button
                  onClick={() => pinHero(null)}
                  disabled={saving}
                  className="px-3 py-1.5 text-xs border border-white/20 text-gray-400 hover:text-white hover:border-white/40 transition-colors flex items-center gap-1 disabled:opacity-40"
                >
                  <PinOff size={12} /> 取消钉定
                </button>
              </div>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setHeroPickerOpen(true)}
            disabled={saving}
            className="w-full py-8 border border-dashed border-white/15 text-sm text-gray-400 hover:text-primary hover:border-primary/50 transition-colors flex items-center justify-center gap-2"
          >
            <Pin size={16} /> 选择影片钉为首屏大海报
          </button>
        )}
      </div>

      {/* Sections 区 */}
      <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-lg font-['Orbitron'] font-bold text-white flex items-center gap-2">
            <Hash size={18} /> 首页分类区块
          </h3>
          <div className="flex gap-2">
            <button
              onClick={addSection}
              className="px-3 py-1.5 text-xs border border-primary/50 text-primary hover:bg-primary hover:text-black transition-colors flex items-center gap-1"
            >
              <Plus size={14} /> 新增分类
            </button>
            <button
              onClick={saveAll}
              disabled={!dirty || saving}
              className="px-4 py-1.5 text-xs font-bold border border-primary text-primary hover:bg-primary hover:text-black disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {saving ? '保存中…' : dirty ? '保存全部' : '已保存'}
            </button>
          </div>
        </div>
        <p className="text-xs text-gray-500 mb-4 leading-relaxed">
          拖动左侧把手调整顺序。每个分类可以选 latest（按 genre 自动取最新）或 custom（手挑影片）。
        </p>

        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={config.sections.map((s) => s.key)} strategy={verticalListSortingStrategy}>
            <div className="space-y-3">
              {config.sections.map((sec) => (
                <SortableSectionRow
                  key={sec.key}
                  section={sec}
                  genres={genres}
                  customMovies={customCache[sec.key] || []}
                  onUpdate={(patch) => updateSection(sec.key, patch)}
                  onRemove={() => removeSection(sec.key)}
                  onPickCustom={() => setCustomPickerForKey(sec.key)}
                />
              ))}
              {config.sections.length === 0 && (
                <div className="text-center py-8 text-sm text-gray-500 border border-dashed border-white/10">
                  还没有分类。点上方"新增分类"开始定制。
                </div>
              )}
            </div>
          </SortableContext>
        </DndContext>
      </div>

      <MoviePickerModal
        open={heroPickerOpen}
        title="选择首屏大海报影片"
        mode="single"
        initialSelected={config.hero_movie_id ? [config.hero_movie_id] : []}
        onClose={() => setHeroPickerOpen(false)}
        onPick={(id) => pinHero(id)}
      />
      {customPickerForKey && (
        <MoviePickerModal
          open={true}
          title={`挑选影片 — ${config.sections.find((s) => s.key === customPickerForKey)?.title || ''}`}
          mode="multi"
          initialSelected={config.sections.find((s) => s.key === customPickerForKey)?.movie_ids || []}
          onClose={() => setCustomPickerForKey(null)}
          onPick={(ids, movies) => {
            updateSection(customPickerForKey, { movie_ids: ids });
            setCustomCache((prev) => ({ ...prev, [customPickerForKey]: movies }));
          }}
        />
      )}
    </div>
  );
};

interface SortableSectionRowProps {
  section: HomepageSectionConfig;
  genres: string[];
  customMovies: Movie[];
  onUpdate: (patch: Partial<HomepageSectionConfig>) => void;
  onRemove: () => void;
  onPickCustom: () => void;
}

const SortableSectionRow: React.FC<SortableSectionRowProps> = ({
  section, genres, customMovies, onUpdate, onRemove, onPickCustom,
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: section.key });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  const limitOptions = useMemo(() => Array.from({ length: 20 }, (_, i) => i + 1), []);

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`border border-white/10 ${section.enabled ? 'bg-black/30' : 'bg-black/10 opacity-60'} transition-colors`}
    >
      <div className="flex items-stretch">
        <button
          {...attributes}
          {...listeners}
          aria-label="拖动调整顺序"
          className="px-2 flex items-center justify-center text-gray-500 hover:text-white cursor-grab active:cursor-grabbing border-r border-white/10"
        >
          <GripVertical size={16} />
        </button>
        <div className="flex-1 p-4 space-y-3">
          {/* 标题行 */}
          <div className="flex gap-3 items-center">
            <input
              type="text"
              value={section.title}
              onChange={(e) => onUpdate({ title: e.target.value })}
              placeholder="分类标题"
              className="flex-1 bg-black/40 border border-white/10 px-3 py-1.5 text-sm text-white focus:border-primary outline-none"
            />
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300 select-none">
              <input
                type="checkbox"
                checked={section.enabled}
                onChange={(e) => onUpdate({ enabled: e.target.checked })}
                className="accent-primary"
              />
              启用
            </label>
            <button
              onClick={onRemove}
              className="text-gray-500 hover:text-red-400 transition-colors p-1"
              title="删除分类"
            >
              <Trash2 size={14} />
            </button>
          </div>

          {/* 模式切换 */}
          <div className="flex items-center gap-4 text-xs">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="radio"
                name={`mode-${section.key}`}
                checked={section.mode === 'latest'}
                onChange={() => onUpdate({ mode: 'latest' })}
                className="accent-primary"
              />
              <span className={section.mode === 'latest' ? 'text-primary' : 'text-gray-400'}>
                latest（按 genre 自动）
              </span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="radio"
                name={`mode-${section.key}`}
                checked={section.mode === 'custom'}
                onChange={() => onUpdate({ mode: 'custom' })}
                className="accent-primary"
              />
              <span className={section.mode === 'custom' ? 'text-primary' : 'text-gray-400'}>
                custom（手挑）
              </span>
            </label>
          </div>

          {/* mode = latest 子选项 */}
          {section.mode === 'latest' && (
            <div className="flex items-center gap-3 text-xs">
              <label className="text-gray-400">分类:</label>
              <select
                value={section.genre || ''}
                onChange={(e) => {
                  const newGenre = e.target.value;
                  // 如果 title 还跟当前 genre 同名（说明用户没改过 title，是默认跟随），
                  // 那就一起把 title 同步到新 genre；用户已经自定义过 title 的就保留。
                  const patch: Partial<HomepageSectionConfig> = { genre: newGenre };
                  if (section.title === (section.genre || '') && newGenre) {
                    patch.title = newGenre;
                  }
                  onUpdate(patch);
                }}
                className="bg-black/40 border border-white/10 px-2 py-1 text-white text-xs outline-none"
              >
                <option value="">（不限）</option>
                {genres.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
              <label className="text-gray-400 ml-3">数量:</label>
              <select
                value={section.limit}
                onChange={(e) => onUpdate({ limit: parseInt(e.target.value, 10) })}
                className="bg-black/40 border border-white/10 px-2 py-1 text-white text-xs outline-none"
              >
                {limitOptions.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
          )}

          {/* mode = custom 子选项 */}
          {section.mode === 'custom' && (
            <div className="space-y-2">
              <div className="flex items-center gap-3 text-xs">
                <button
                  onClick={onPickCustom}
                  className="px-3 py-1 border border-primary/50 text-primary hover:bg-primary hover:text-black transition-colors flex items-center gap-1"
                >
                  <Star size={12} /> 选择影片（{section.movie_ids?.length || 0}）
                </button>
                {(section.movie_ids?.length || 0) === 0 && (
                  <span className="text-amber-400">至少选 1 部影片才能保存</span>
                )}
              </div>
              {customMovies.length > 0 && (
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {customMovies.map((m) => (
                    <div
                      key={m.id}
                      className="w-16 aspect-[2/3] flex-shrink-0 bg-gray-900 border border-white/10 overflow-hidden"
                      title={m.title}
                    >
                      {m.cover_url && (
                        <img src={m.cover_url} alt={m.title} referrerPolicy="no-referrer" className="w-full h-full object-cover" />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
