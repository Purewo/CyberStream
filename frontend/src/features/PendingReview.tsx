// CyberStream 审查工作台 · 待审批 tab
//
// 后端 1.21 起把"可疑刮削结果"（placeholder / local_only / low_confidence /
// fallback_pipeline_match / poster_missing 等）默认放进
// catalog_visibility.effective_status='pending_review' 池子，不进普通影视库。
//
// 这个组件做的事：
//   1. GET /v1/metadata/work-items?effective_status=pending_review 拉列表
//   2. 渲染卡片（海报 / 标题 / issue 标签 / 选中态）
//   3. 多选 + 一键全选
//   4. 「批量入库」→ POST /v1/metadata/pending-review/publish
//      - 普通发布失败（带 blockers）时支持「强制发布」二次确认
//   5. 单条「忽略 / 隐藏」也走同接口 + status=hidden（暂不实现，等用户需求）
//
// 关键约束（来自需求）：
//   - 刮削入口绝不许"刮削+入库"一键化，所有入库必须经过这个 tab 人工确认
//   - 默认不展示"force=true"按钮，避免用户无脑发布有 blocker 的条目

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Check, RefreshCw, ShieldCheck, Square, CheckSquare, Image as ImageIcon, AlertCircle, ExternalLink, Sparkles } from 'lucide-react';
import { movieService } from '../api';
import { resolveAssetUrl } from '../api/core';
import { toast } from '../utils';
import type { Movie } from '../types';

interface PendingReviewItem {
  id: string;
  title: string;
  original_title?: string;
  year?: number;
  poster_url?: string;
  poster_asset_url?: string;
  backdrop_url?: string;
  scraper_source?: string;
  catalog_visibility?: import('../types').CatalogVisibility;
  metadata_state?: import('../types').MetadataState;
  metadata_issues?: Array<{ code: string; label?: string; count?: number; severity?: string }>;
  metadata_diagnostics?: any;
}

// 后端 re-scrape/plan 每条返回的预览结构（1.21+，见 OpenAPI MetadataReScrapePlanItem）。
// 重点是 search_title / search_year / search_query / entity_context——后端把"路径
// 原本猜成什么"和"这次实际拿去搜的关键词"都摊开了，前端据此渲染可编辑预览。
interface ReScrapePlanItem {
  movie_id: string;
  title?: string | null;
  scraper_source?: string | null;
  // 本次实际用于搜索的关键词（后端已直接拆好，方便绑输入框）
  search_title?: string | null;
  search_year?: number | null;
  search_query?: any;
  // 路径解析结果："后端原本猜成什么"
  entity_context?: {
    title?: string;
    year?: number | null;
    media_type_hint?: string | null;
    parse_layer?: string;
    parse_strategy?: string;
    sample_path?: string | null;
    resource_count?: number;
  };
  apply_item?: {
    id?: string;
    movie_id?: string;
    media_type_hint?: string | null;
    search_title?: string | null;
    search_year?: number | null;
    metadata_unlocked_fields?: string[];
  };
}

// 用户在预览面板里的编辑草稿：每条可改标题 / 年份 / 类型。
interface ReScrapeDraft {
  movie_id: string;
  original_guess: string;      // entity_context.title，只读展示
  search_title: string;        // 可编辑
  search_year: string;         // 可编辑（字符串，空=清除年份）
  media_type_hint: '' | 'movie' | 'tv';
}

const ISSUE_LABEL_CN: Record<string, string> = {
  fallback_pipeline_match: '兜底匹配',
  placeholder_metadata: '占位元数据',
  local_only_metadata: '仅本地元数据',
  low_confidence_resources: '低置信资源',
  poster_missing: '缺海报',
  overview_missing: '缺简介',
  metadata_needs_attention: '需复核',
  duplicate_episode_numbers: '重复集号',
  episode_count_mismatch: '集数不一致',
  episode_number_missing: '缺集号',
  missing_episode_numbers: '缺失集号',
  season_metadata_missing: '缺季元数据',
  title_missing: '缺标题',
};

// 后端把 issue 拆成两类，前端在 UI 上要合并展示成"为什么进审查 + 建议怎么办"。
//   hard blocker：必须重新识别才能补齐（缺标题、缺海报）。这种条目即使 force=true
//                 入库也是空壳，禁止"确认无误并入库"。
//   soft blocker：识别结果存疑但元数据齐全（needs_attention / 兜底匹配 / 占位）。
//                 用户人工核对后可以「确认无误并入库」走 force=true 旁路；也可以
//                 选择重新识别试图换个 provider。
// 注：title_missing / poster_missing 两个属硬阻断；其他默认软阻断。
const HARD_BLOCKERS = new Set(['title_missing', 'poster_missing']);
const isHardBlocker = (code: string) => HARD_BLOCKERS.has(code);

// 单条 reason 的"建议动作"——给用户看清楚每个标签该走哪条路径。
const REASON_ACTION_CN: Record<string, string> = {
  title_missing: '建议重新识别',
  poster_missing: '建议重新识别',
  metadata_needs_attention: '可人工确认',
  fallback_pipeline_match: '建议复核 / 重新识别',
  placeholder_metadata: '建议重新识别',
  local_only_metadata: '建议补全元数据',
  low_confidence_resources: '建议重新识别',
};

const localizeIssue = (code: string, fallback?: string) =>
  ISSUE_LABEL_CN[code] || fallback || code;

// 待审批工具条的统一动作按钮。三个按钮（刷新/确认入库/批量重新识别）共用它，
// 保证完全同级：相同尺寸、字重、边框、特效。配色与辉光全部走 inline style +
// CSS 变量，绕开 Tailwind CDN 不生成带透明度 utility 的限制（之前 text-primary/90
// 这类类名压根没产出，导致按钮变灰）。特效：hover 抬升 + 霓虹辉光 + 一道扫光划过。
const ActionButton: React.FC<{
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  icon: React.ReactNode;
  label: string;
  count?: number;
}> = ({ onClick, disabled, title, icon, label, count }) => {
  const [hover, setHover] = useState(false);
  const active = hover && !disabled;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="relative overflow-hidden flex items-center gap-2 px-3.5 py-2 rounded font-['Orbitron'] font-semibold tracking-widest text-xs transition-all duration-200 ease-out disabled:cursor-not-allowed"
      style={{
        border: '1px solid',
        borderColor: disabled
          ? 'rgba(255,255,255,0.1)'
          : active ? 'var(--color-primary)' : 'rgba(0,243,255,0.4)',
        backgroundColor: disabled
          ? 'transparent'
          : active ? 'rgba(0,243,255,0.12)' : 'rgba(0,243,255,0.05)',
        color: disabled
          ? 'rgb(107,114,128)'
          : active ? 'var(--color-primary)' : 'rgba(0,243,255,0.85)',
        boxShadow: active ? '0 0 18px var(--color-primary)' : 'none',
        transform: active ? 'translateY(-2px)' : 'translateY(0)',
        opacity: disabled ? 0.45 : 1,
      }}
    >
      {/* 扫光条：hover 时从左滑到右 */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 w-1/2 -skew-x-12"
        style={{
          left: active ? '150%' : '-60%',
          background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent)',
          transition: 'left 0.7s ease-out',
          display: disabled ? 'none' : 'block',
        }}
      />
      {icon}
      {label}
      {count != null && count > 0 && (
        <span
          className="relative px-1.5 py-0.5 rounded text-[10px] font-bold"
          style={{
            backgroundColor: 'rgba(0,243,255,0.25)',
            color: 'var(--color-primary)',
            boxShadow: active ? '0 0 6px var(--color-primary)' : 'none',
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
};

export const PendingReview: React.FC<{ onEditMetadata?: (m: Movie) => void }> = ({ onEditMetadata }) => {
  const [items, setItems] = useState<PendingReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [publishing, setPublishing] = useState(false);
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState<any>(null);
  const [forceConfirm, setForceConfirm] = useState<{ failed: any[]; ids: string[] } | null>(null);
  // 重刮预览面板：plan 条目 / 用户编辑草稿（按 movie_id 索引）/ 提交中
  const [planItems, setPlanItems] = useState<ReScrapePlanItem[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ReScrapeDraft>>({});
  const [submittingJob, setSubmittingJob] = useState(false);

  const PAGE_SIZE = 30;

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const data = await movieService.getPendingReviewItems(page, PAGE_SIZE);
      setItems(data.items as PendingReviewItem[]);
      setMeta(data.meta);
      // 翻页时保留选中态意义不大（用户预期当前页操作），清掉
      setSelectedIds(new Set());
    } catch (e) {
      console.error('[PendingReview] load failed', e);
      toast.error('加载待审批列表失败');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  // 监听全局后台 job 完成事件：重刮成功后条目元数据补齐，刷新待审批列表
  // （识别干净的会从待审批池里出列）。重刮单条要几十秒，必须等 finished 再刷，
  // 提交时立即刷新只会看到旧状态。movie-updated 通知其他视图同步。
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ status?: string }>).detail;
      if (!detail) return;
      if (detail.status === 'succeeded' || detail.status === 'failed') {
        loadItems();
        window.dispatchEvent(new CustomEvent('movie-updated'));
      }
    };
    window.addEventListener('cyber:job:finished', handler);
    return () => window.removeEventListener('cyber:job:finished', handler);
  }, [loadItems]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((it) => it.id)));
    }
  };

  // 批量入库主入口。默认 force=false：后端会把带 blockers 的条目放进
  // failed[]，reason 区分三种：
  //   - requires_force: 有 blocker（如 metadata_needs_attention / poster_missing），
  //     需要用户二次确认强制发布
  //   - not_found: 影片已被删除，刷新列表即可消失
  //   - not_pending_review: 已不在待审批池（多端并发改动），刷新列表即可
  // 只对 requires_force 弹二次确认；另两种直接 toast + 刷新。
  const handlePublish = async (ids: string[], force: boolean) => {
    if (ids.length === 0) return;
    setPublishing(true);
    try {
      const res = await movieService.publishPendingReview(ids, force);
      if (!res.ok) {
        toast.error(res.msg || '批量发布失败');
        return;
      }
      const data = res.data || {};
      const published: any[] = data.published || [];
      const failed: any[] = data.failed || [];

      if (published.length > 0) {
        toast.success(`已发布 ${published.length} 条到普通影视库`);
      }

      // 把失败按 reason 分桶
      const requiresForce = failed.filter((f: any) => f.reason === 'requires_force');
      const stale = failed.filter((f: any) => f.reason === 'not_found' || f.reason === 'not_pending_review');
      const otherFailed = failed.filter((f: any) =>
        f.reason !== 'requires_force' && f.reason !== 'not_found' && f.reason !== 'not_pending_review',
      );

      if (stale.length > 0) {
        toast.error(`${stale.length} 条已被删除或不在待审批池，已自动跳过`);
      }
      if (otherFailed.length > 0) {
        toast.error(`${otherFailed.length} 条因后端硬性拒绝未发布`);
      }
      if (requiresForce.length > 0 && !force) {
        // 仅有 blocker 的退到这里：弹二次确认让用户决定 force=true
        setForceConfirm({
          failed: requiresForce,
          ids: requiresForce.map((f: any) => f.movie_id || f.id).filter(Boolean),
        });
      } else if (requiresForce.length > 0) {
        // 已经 force=true 了还在 requires_force —— 不该出现，但兜底提示
        toast.error(`仍有 ${requiresForce.length} 条无法强制发布，请人工处理`);
      }

      await loadItems();
    } finally {
      setPublishing(false);
    }
  };

  const handleConfirmForce = async () => {
    if (!forceConfirm) return;
    const ids = forceConfirm.ids;
    setForceConfirm(null);
    await handlePublish(ids, true);
  };

  // 「批量重新识别」——主操作。后端 1.21 推荐工作流是先重识别补元数据，
  // 入库只对已经识别干净的条目做。和「确认入库」是互斥的两条路径。
  // 流程：
  //   1) POST /v1/metadata/re-scrape/plan 预览（dry-run，不写库）
  //   2) 弹预览面板：列出每条「后端原本猜成什么」+ 可编辑的搜索标题/年份
  //   3) 用户确认/修正后，带 search_title/search_year 提交 jobs 起后台任务
  //   4) toast 提示「已加入后台队列」，刷新列表（识别完后端会更新 issue / 出池）
  // 这是核心：单纯重刮（关键词不变）对解析错的条目毫无意义——失败的还会再失败。
  // 必须让用户先看清后端拿什么关键词去搜、能改了再刮。后端 1.21 已支持 items[]
  // 携带 search_title/search_year（见 OpenAPI MovieMetadataBatchReScrapeItemRequest）。
  const [reScraping, setReScraping] = useState(false);
  const handleBatchReScrape = async (ids: string[]) => {
    if (ids.length === 0) return;
    setReScraping(true);
    try {
      const plan = await movieService.planBatchReScrapeMetadata({ movie_ids: ids });
      const planItemsRaw: ReScrapePlanItem[] = plan?.items || [];
      if (planItemsRaw.length === 0) {
        toast.error('预览计划为空，无法重新识别');
        return;
      }
      // 用 plan 返回的 search_title/year（后端已拆好）初始化每条草稿；
      // 没有则回退 entity_context.title / 列表项 title。
      const draftMap: Record<string, ReScrapeDraft> = {};
      for (const it of planItemsRaw) {
        const mid = it.movie_id || it.apply_item?.movie_id || it.apply_item?.id || '';
        if (!mid) continue;
        const guess = it.entity_context?.title || it.title || '';
        const initTitle = it.search_title ?? it.apply_item?.search_title ?? guess ?? '';
        const initYear = it.search_year ?? it.apply_item?.search_year ?? it.entity_context?.year ?? null;
        const initType = (it.apply_item?.media_type_hint || it.entity_context?.media_type_hint || '') as ReScrapeDraft['media_type_hint'];
        draftMap[mid] = {
          movie_id: mid,
          original_guess: guess,
          search_title: initTitle || '',
          search_year: initYear == null ? '' : String(initYear),
          media_type_hint: initType === 'movie' || initType === 'tv' ? initType : '',
        };
      }
      setPlanItems(planItemsRaw);
      setDrafts(draftMap);
    } catch (e) {
      console.error('[PendingReview] plan failed', e);
      toast.error('获取重识别预览失败');
    } finally {
      setReScraping(false);
    }
  };

  const updateDraft = (movieId: string, patch: Partial<ReScrapeDraft>) => {
    setDrafts((prev) => ({ ...prev, [movieId]: { ...prev[movieId], ...patch } }));
  };

  const closePlan = () => {
    setPlanItems(null);
    setDrafts({});
  };

  // 提交重刮 job：把用户编辑过的草稿转成后端 items[]。
  // - search_title 必填（空标题搜不出东西，拦掉）
  // - search_year 空字符串 → 传 null，显式清除路径误判的年份
  // - media_type_hint 空 → 不传，让后端自己判定
  const submitReScrapeJob = async () => {
    const apiItems = (Object.values(drafts) as ReScrapeDraft[])
      .map((d) => {
        const title = d.search_title.trim();
        if (!title) return null;
        const yearTrim = d.search_year.trim();
        const item: any = { id: d.movie_id, search_title: title };
        item.search_year = yearTrim === '' ? null : Number(yearTrim);
        if (d.media_type_hint) item.media_type_hint = d.media_type_hint;
        return item;
      })
      .filter(Boolean);

    if (apiItems.length === 0) {
      toast.error('请至少为一条填写搜索标题');
      return;
    }
    setSubmittingJob(true);
    try {
      const job = await movieService.startBatchReScrapeMetadataJob({ items: apiItems });
      // job 响应形如 { job: { id, ... } }；兼容扁平 { id }。
      const jobId = (job as any)?.job?.id || (job as any)?.id;
      if (jobId) {
        toast.success(`已提交 ${apiItems.length} 条重新识别任务`);
        closePlan();
        // 接入全局进度条：重刮单条要跑几十秒，必须给可见进度，否则用户以为没反应。
        // 不在这里 loadItems——等 cyber:job:finished 再刷新，那时结果才落库。
        window.dispatchEvent(new CustomEvent('cyber:job:started', {
          detail: { jobId, label: `批量重新识别 (${apiItems.length} 条)` },
        }));
      } else if (job) {
        // 后端没回 job_id（不该发生），兜底延迟刷新一次。
        toast.success(`已提交 ${apiItems.length} 条重新识别任务，后台执行中`);
        closePlan();
        setTimeout(() => loadItems(), 1000);
      } else {
        toast.error('后台任务提交失败，请稍后重试');
      }
    } catch (e) {
      console.error('[PendingReview] re-scrape job failed', e);
      toast.error('提交重识别任务失败');
    } finally {
      setSubmittingJob(false);
    }
  };

  // 选中条目里能直接 force 入库的——所有 blocker 都是 soft 的（即不含
  // title_missing / poster_missing），其余必须先去重识别。后端 force=true
  // 路径只对 metadata_needs_attention 才稳，对硬阻断条目入库后是空壳。
  const publishableSelectedIds = useMemo(() => {
    return items
      .filter((it) => selectedIds.has(it.id))
      .filter((it) => {
        const blockers = it.catalog_visibility?.blockers || [];
        // 完全无 blocker → 后端会按 auto 通过；有 blocker 但全是 soft → force 后入库；
        // 有任意一个 hard → 拦掉，引导走重识别。
        return blockers.every((b) => !isHardBlocker(b));
      })
      .map((it) => it.id);
  }, [items, selectedIds]);
  const blockedSelectedCount = selectedIds.size - publishableSelectedIds.length;

  // 后端 pagination 字段：{current_page, page_size, total_items, total_pages}
  // 兼容老 meta.pages（旧版本叫法）。
  const totalPages = meta?.total_pages ?? meta?.pages ?? 1;
  const totalItems = meta?.total_items ?? null;

  // 三个操作按钮共用 ActionButton 组件——保证完全同级（同尺寸/字重/特效）。
  // 配色和辉光走 inline style + CSS 变量，绕开 Tailwind CDN 不生成带透明度
  // utility（text-primary/90、bg-primary/5、shadow-[…var()]）的老毛病。
  // 特效：默认深底青边，hover 抬升 + 霓虹辉光 + 一道扫光划过，active 下压。

  return (
    <div className="space-y-4">
      {/* 顶部工具条 — 主操作是「批量重新识别」，「确认入库」降级为次要按钮，
          原因见 [[force-path-demoted]] / 后端 1.21 待审批 UX 建议 */}
      <div className="flex flex-wrap items-center gap-3 p-4 rounded-xl border border-primary/20 bg-[#0a0a12]/80">
        <button
          onClick={toggleSelectAll}
          disabled={items.length === 0}
          className="flex items-center gap-2 text-sm font-['Rajdhani'] text-gray-300 hover:text-primary disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {selectedIds.size === items.length && items.length > 0
            ? <CheckSquare size={16} className="text-primary" />
            : <Square size={16} />}
          {selectedIds.size === items.length && items.length > 0 ? '取消全选' : '全选当前页'}
        </button>

        <div className="text-xs text-gray-500 font-['Rajdhani']">
          已选 <span className="text-primary font-bold">{selectedIds.size}</span> / 当前页 {items.length}
          {totalItems != null && (
            <span className="ml-2 text-gray-600">· 共 {totalItems} 条待审批</span>
          )}
        </div>

        <div className="flex-1"></div>

        <ActionButton
          onClick={loadItems}
          disabled={loading}
          title="刷新列表"
          icon={<RefreshCw size={13} className={loading ? 'animate-spin' : ''} />}
          label="刷新"
        />

        {/* 次要：确认入库。仅对 publishableSelectedIds（不含硬阻断）启用，避免
            用户对缺标题/缺海报的条目 force 出空壳记录。文案改成"确认入库"
            而非"批量入库"——强调它是精挑细选后的确认动作。 */}
        <ActionButton
          onClick={() => handlePublish(publishableSelectedIds, false)}
          disabled={publishing || publishableSelectedIds.length === 0}
          title={blockedSelectedCount > 0
            ? `${blockedSelectedCount} 条因缺标题/缺海报无法直接入库，请先重新识别`
            : '将选中条目发布到普通影视库'}
          icon={publishing ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
          label="确认入库"
          count={publishableSelectedIds.length}
        />

        {/* 主操作：批量重识别。三个按钮完全同级——共用 ActionButton，特效一致。 */}
        <ActionButton
          onClick={() => handleBatchReScrape(Array.from(selectedIds))}
          disabled={reScraping || selectedIds.size === 0}
          title="送回管线重新匹配元数据（推荐：能修复缺海报 / 缺标题 / 占位等问题）"
          icon={reScraping ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          label="批量重新识别"
          count={selectedIds.size}
        />
      </div>

      {/* 列表 */}
      {loading && items.length === 0 ? (
        <div className="flex items-center gap-2 text-primary/70 p-12 justify-center">
          <Loader2 className="animate-spin w-4 h-4" /> 正在加载待审批条目...
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="p-4 border-2 border-primary/40 rounded-2xl bg-primary/5 mb-4 shadow-[0_0_20px_rgba(0,243,255,0.15)]">
            <ShieldCheck className="w-12 h-12 text-primary" strokeWidth={1.2} />
          </div>
          <h3 className="text-lg font-['Orbitron'] text-white tracking-widest">没有待审批条目</h3>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {items.map((item) => {
            const selected = selectedIds.has(item.id);
            const issues = item.metadata_issues || [];
            const blockers = item.catalog_visibility?.blockers || [];
            const poster = item.poster_asset_url ? resolveAssetUrl(item.poster_asset_url) : item.poster_url;
            // 合并 blocker / issue 成"待处理原因"。同 code 去重——后端经常把
            // poster_missing 同时塞到 blockers 和 metadata_issues 里。
            // tone 取自 isHardBlocker：硬阻断标红（必须重识别），其余琥珀。
            const seen = new Set<string>();
            const reasonCodes: string[] = [];
            for (const code of [...blockers, ...issues.map((it) => it.code)]) {
              if (!code || seen.has(code)) continue;
              seen.add(code);
              reasonCodes.push(code);
            }
            const chips = reasonCodes.map((code) => ({
              code,
              tone: isHardBlocker(code) ? ('hard' as const) : ('soft' as const),
            }));
            return (
              <div
                key={item.id}
                className={`group relative aspect-[2/3] rounded-lg overflow-hidden border transition-all cursor-pointer ${selected
                  ? 'border-primary shadow-[0_0_15px_rgba(0,243,255,0.4)] scale-[1.02] z-10'
                  : 'border-white/10 hover:border-primary/60 hover:shadow-[0_0_15px_rgba(0,243,255,0.2)] hover:scale-[1.02] hover:z-10'}`}
                onClick={() => {
                  if (!onEditMetadata) {
                    toast.error('元数据编辑器未挂载，请重启页面');
                    return;
                  }
                  onEditMetadata(item as unknown as Movie);
                }}
              >
                {/* 海报 — 全卡片背景，跟普通影视库视觉一致 */}
                <div className="absolute inset-0 bg-gradient-to-br from-[#1a1a20] to-black">
                  {poster ? (
                    <img
                      src={poster}
                      alt={item.title}
                      referrerPolicy="no-referrer"
                      loading="lazy"
                      className="absolute inset-0 w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                    />
                  ) : (
                    // 缺海报 fallback：只放一个大图标占位，标题已经在底部蒙层
                    // 显示，这里再印一次会跟蒙层文字重叠成一团乱
                    <div className="absolute inset-0 flex items-center justify-center">
                      <ImageIcon className="w-12 h-12 text-white/15" strokeWidth={1.2} />
                    </div>
                  )}
                </div>

                {/* 顶部蒙层：年份 / 来源 — 只在 hover 时清晰显示，避免抢占封面 */}
                <div className="absolute top-0 inset-x-0 h-16 bg-gradient-to-b from-black/80 via-black/40 to-transparent pointer-events-none"></div>
                <div className="absolute top-2 left-2 right-10 flex items-center gap-1.5 text-[10px] font-['Rajdhani'] tracking-widest text-white/80">
                  {item.year && <span>{item.year}</span>}
                  {item.scraper_source && (
                    <>
                      <span className="text-white/30">·</span>
                      <span
                        style={{ color: '#fcd34d' }}
                        className="truncate font-mono text-[9px]"
                      >
                        {item.scraper_source}
                      </span>
                    </>
                  )}
                </div>

                {/* 选中态 checkbox：右上角，独立点击区不冒泡到卡片 */}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); toggleSelect(item.id); }}
                  title={selected ? '取消选中' : '选中'}
                  className={`absolute top-2 right-2 z-20 w-7 h-7 flex items-center justify-center rounded transition-all ${selected
                    ? 'bg-primary text-black shadow-[0_0_8px_rgba(0,243,255,0.6)]'
                    : 'bg-black/60 text-white/70 hover:bg-primary/30 hover:text-primary backdrop-blur-sm border border-white/20'}`}
                >
                  {selected ? <Check size={14} strokeWidth={3} /> : <Square size={14} />}
                </button>

                {/* 底部信息层：标题 + 标签。永远可见，hover 时背景加深 */}
                <div className="absolute bottom-0 inset-x-0 p-2.5 bg-gradient-to-t from-black via-black/85 to-transparent">
                  <h4
                    className="text-sm font-['Orbitron'] font-bold text-white tracking-tight line-clamp-2 leading-snug group-hover:text-primary transition-colors"
                    title={item.title}
                  >
                    {item.title}
                  </h4>
                  {chips.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {chips.slice(0, 3).map((chip, i) => {
                        const action = REASON_ACTION_CN[chip.code];
                        const fullTip = action
                          ? `${localizeIssue(chip.code)} · ${action}`
                          : localizeIssue(chip.code);
                        return (
                          <span
                            key={`${chip.code}-${i}`}
                            title={fullTip}
                            style={{
                              display: 'inline-block',
                              whiteSpace: 'nowrap',
                              fontSize: '10px',
                              fontFamily: "'Rajdhani', sans-serif",
                              fontWeight: 700,
                              lineHeight: 1.2,
                              padding: '1px 5px',
                              borderRadius: 3,
                              border: chip.tone === 'hard'
                                ? '1px solid rgba(239, 68, 68, 0.6)'
                                : '1px solid rgba(245, 158, 11, 0.55)',
                              backgroundColor: chip.tone === 'hard'
                                ? 'rgba(239, 68, 68, 0.2)'
                                : 'rgba(245, 158, 11, 0.18)',
                              color: chip.tone === 'hard' ? '#fca5a5' : '#fcd34d',
                            }}
                          >
                            {localizeIssue(chip.code)}
                          </span>
                        );
                      })}
                      {chips.length > 3 && (
                        <span style={{ fontSize: '10px', color: '#9ca3af', fontFamily: 'monospace', padding: '1px 4px' }}>
                          +{chips.length - 3}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* hover 时左下角悬浮提示 + 阻断徽章 — 让用户知道这张卡可点开编辑器 */}
                <div className="absolute bottom-0 inset-x-0 p-2.5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none flex justify-end items-end">
                  <span className="flex items-center gap-1 text-[10px] text-primary font-['Rajdhani'] tracking-widest bg-black/70 px-1.5 py-0.5 rounded backdrop-blur-sm">
                    <ExternalLink size={10} /> 编辑
                  </span>
                </div>

              </div>
            );
          })}
        </div>
      )}

      {/* 翻页 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
            className="px-3 py-1.5 text-xs font-['Orbitron'] tracking-widest text-gray-400 border border-white/10 rounded hover:border-primary/60 hover:text-primary transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            上一页
          </button>
          <span className="text-xs text-gray-500 font-['Rajdhani'] px-2">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
            className="px-3 py-1.5 text-xs font-['Orbitron'] tracking-widest text-gray-400 border border-white/10 rounded hover:border-primary/60 hover:text-primary transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            下一页
          </button>
        </div>
      )}

      {/* 重刮预览 + 关键词编辑面板。核心：让用户在重刮前看清/修正搜索关键词，
          避免关键词不变的无意义重刮。每条展示「后端原本猜成什么」+ 可编辑标题/年份。 */}
      {planItems && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div
            className="relative bg-[#0a0a12] rounded-xl w-[760px] max-w-[96vw] max-h-[88vh] flex flex-col"
            style={{ border: '1px solid rgba(0,243,255,0.4)', boxShadow: '0 0 30px rgba(0,243,255,0.18)' }}
          >
            {/* 头部 */}
            <div className="p-5 border-b border-white/10">
              <h3 className="text-base font-['Orbitron'] font-bold tracking-widest mb-1.5 flex items-center gap-2" style={{ color: 'var(--color-primary)' }}>
                <Sparkles size={18} /> 重新识别预览 · 确认搜索关键词
              </h3>
              <p className="text-xs text-gray-400 font-['Rajdhani'] leading-relaxed">
                下面是后端从文件路径解析出的关键词。<span className="text-gray-200">关键词不变，重刮结果不会变</span>——
                请核对并修正标题 / 年份后再提交。留空年份表示让后端忽略路径年份。
              </p>
            </div>

            {/* 条目列表 */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-3">
              {planItems.map((it) => {
                const mid = it.movie_id || it.apply_item?.movie_id || it.apply_item?.id || '';
                const draft = drafts[mid];
                if (!draft) return null;
                const guess = draft.original_guess || it.title || '(无解析标题)';
                const samplePath = it.entity_context?.sample_path;
                return (
                  <div key={mid} className="rounded-lg border border-white/10 bg-black/30 p-3">
                    {/* 后端原本猜成什么 */}
                    <div className="flex items-start gap-2 mb-2.5">
                      <span className="text-[10px] font-mono text-gray-500 mt-1 shrink-0">原解析</span>
                      <div className="min-w-0">
                        <div className="text-sm text-gray-300 font-['Rajdhani'] truncate" title={guess}>
                          {guess}
                          {it.entity_context?.year != null && <span className="text-gray-500 ml-1">({it.entity_context.year})</span>}
                        </div>
                        {samplePath && (
                          <div className="text-[10px] font-mono text-gray-600 truncate mt-0.5" title={samplePath}>{samplePath}</div>
                        )}
                      </div>
                    </div>
                    {/* 可编辑：搜索标题 / 年份 / 类型 */}
                    <div className="flex flex-wrap gap-2 items-center">
                      <input
                        type="text"
                        value={draft.search_title}
                        onChange={(e) => updateDraft(mid, { search_title: e.target.value })}
                        placeholder="搜索标题"
                        className="flex-1 min-w-[180px] bg-[#11111a] border border-white/15 focus:border-primary focus:outline-none rounded px-2.5 py-1.5 text-sm text-white font-['Rajdhani'] transition-colors"
                        style={{ caretColor: 'var(--color-primary)' }}
                      />
                      <input
                        type="number"
                        value={draft.search_year}
                        onChange={(e) => updateDraft(mid, { search_year: e.target.value })}
                        placeholder="年份"
                        className="w-20 bg-[#11111a] border border-white/15 focus:border-primary focus:outline-none rounded px-2 py-1.5 text-sm text-white font-['Rajdhani'] transition-colors"
                      />
                      <select
                        value={draft.media_type_hint}
                        onChange={(e) => updateDraft(mid, { media_type_hint: e.target.value as ReScrapeDraft['media_type_hint'] })}
                        className="bg-[#11111a] border border-white/15 focus:border-primary focus:outline-none rounded px-2 py-1.5 text-sm text-gray-200 font-['Rajdhani'] transition-colors"
                      >
                        <option style={{ background: '#0a0a12' }} value="">自动</option>
                        <option style={{ background: '#0a0a12' }} value="movie">电影</option>
                        <option style={{ background: '#0a0a12' }} value="tv">剧集</option>
                      </select>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* 底部操作 */}
            <div className="p-5 border-t border-white/10 flex justify-between items-center">
              <span className="text-xs text-gray-500 font-['Rajdhani']">共 {planItems.length} 条</span>
              <div className="flex gap-2">
                <button
                  onClick={closePlan}
                  disabled={submittingJob}
                  className="px-4 py-2 text-xs font-['Orbitron'] tracking-widest text-gray-400 border border-white/10 rounded hover:border-white/30 hover:text-white transition-all disabled:opacity-40"
                >
                  取消
                </button>
                <button
                  onClick={submitReScrapeJob}
                  disabled={submittingJob}
                  className="px-4 py-2 text-xs font-['Orbitron'] tracking-widest font-bold rounded transition-all flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{ backgroundColor: 'var(--color-primary)', color: '#000', boxShadow: '0 0 15px rgba(0,243,255,0.4)' }}
                >
                  {submittingJob ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  确认并重新识别
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 强制发布二次确认 modal */}
      {forceConfirm && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div
            className="relative bg-[#0a0a12] rounded-xl p-6 w-[480px] max-w-[92vw]"
            style={{ border: '1px solid rgba(245, 158, 11, 0.6)', boxShadow: '0 0 30px rgba(245, 158, 11, 0.25)' }}
          >
            <h3 className="text-base font-['Orbitron'] font-bold text-amber-400 tracking-widest mb-3 flex items-center gap-2">
              <AlertCircle size={18} /> 部分条目存在阻断项
            </h3>
            <p className="text-xs text-gray-400 font-['Rajdhani'] leading-relaxed mb-3">
              下面 <span className="text-amber-400 font-bold">{forceConfirm.failed.length}</span> 条因缺标题、缺海报或元数据需复核未能发布。
              强制发布会绕过这些检查直接进普通影视库——确定要继续吗？
            </p>
            <div className="max-h-48 overflow-y-auto custom-scrollbar bg-black/40 border border-white/5 rounded p-2 mb-4 space-y-1">
              {forceConfirm.failed.slice(0, 20).map((f: any, idx: number) => {
                // 后端 publish 接口的 blockers 是字符串数组（["metadata_needs_attention", "poster_missing"]）
                // 兼容旧的 {code, label} 形状以防契约变动。
                const blockerLabels = (f.blockers || []).map((b: any) => {
                  if (typeof b === 'string') return localizeIssue(b);
                  return localizeIssue(b.code, b.label);
                }).join('、');
                const text = blockerLabels || (f.reason ? `原因：${f.reason}` : '未知原因');
                return (
                  <div key={f.movie_id || idx} className="text-[10px] text-gray-400 font-mono truncate" title={text}>
                    <span className="text-gray-600">·</span> <span className="text-gray-300">{f.movie_id || '(missing id)'}</span> — {text}
                  </div>
                );
              })}
              {forceConfirm.failed.length > 20 && (
                <div className="text-[10px] text-gray-600 font-mono">… 还有 {forceConfirm.failed.length - 20} 条</div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setForceConfirm(null)}
                className="px-4 py-2 text-xs font-['Orbitron'] tracking-widest text-gray-400 border border-white/10 rounded hover:border-white/30 hover:text-white transition-all"
              >
                取消
              </button>
              <button
                onClick={handleConfirmForce}
                className="px-4 py-2 text-xs font-['Orbitron'] tracking-widest font-bold text-black bg-amber-400 hover:bg-amber-300 hover:shadow-[0_0_15px_rgba(245,158,11,0.5)] rounded transition-all flex items-center gap-1.5"
              >
                <Check size={12} /> 强制发布
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
