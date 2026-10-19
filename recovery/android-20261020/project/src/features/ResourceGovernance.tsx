import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import { resourceService } from '../api';
import { toast } from '../utils';

// ── 资源治理面板 ───────────────────────────────────────────────────────────
//
// 视图职责很窄：
//   1. 展示 issue 类型聚合卡片 + 一张明细表
//   2. 让用户挑出需要清理的资源记录（不是物理文件）
//   3. 起后台 job 真正执行清理
//
// 旧版有几处冗余，2026-05 一并收掉：
//   - activeJob state 是死代码 → 改成派 cyber:job:started 走全局进度条
//   - 「生成清理计划 → 执行清理」两步走但中间没审计入口 → 合并成单步弹确认
//   - 单条「处理」按钮跟批量按钮共享 plan state 互相打架 → 改成 checkbox 多选
//   - 「问题」列在过滤生效后变成纯装饰 → 直接拿掉，taxonomy label 移到顶部 chip

interface GovernanceItem {
  issue_code: string;
  resource_ids?: string[];
  resource?: { resource_id: string };
  resource_id?: string;
  resources?: any[];
  source?: any;
  path_check?: { path?: string };
  path?: string;
  movie_title?: string;
  recommendation?: string;
  message?: string;
  info?: string;
  duplicate_key?: any;
  label?: string;
}

const itemKeyOf = (item: GovernanceItem, idx: number): string => {
  const ids = item.resource_ids || (item.resource ? [item.resource.resource_id] : item.resource_id ? [item.resource_id] : []);
  return ids.length > 0 ? ids.join(',') : `__${idx}`;
};

const itemResourceIds = (item: GovernanceItem): string[] => {
  return item.resource_ids || (item.resource ? [item.resource.resource_id] : item.resource_id ? [item.resource_id] : []);
};

export const ResourceGovernance = ({ taxonomy }: { taxonomy?: any }) => {
  const [summary, setSummary] = useState<any>(null);
  const [items, setItems] = useState<GovernanceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [liveCheck, setLiveCheck] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [issueCode, setIssueCode] = useState<string>('all');
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [planning, setPlanning] = useState(false);
  const [pendingPlan, setPendingPlan] = useState<any>(null);
  const [executing, setExecuting] = useState(false);

  const fetchSummary = async () => {
    try {
      const data = await resourceService.getGovernanceSummary(liveCheck);
      setSummary(data);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchItems = async (p = 1) => {
    setLoading(true);
    try {
      const data = await resourceService.listGovernanceItems(p, 20, issueCode === 'all' ? undefined : issueCode, liveCheck);
      setItems(data.items);
      setTotalPages(data.meta?.total_pages || 1);
      setSelectedKeys(new Set());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSummary(); }, [liveCheck]);
  useEffect(() => { fetchItems(page); }, [page, issueCode, liveCheck]);

  useEffect(() => {
    const onUpdate = () => { fetchSummary(); fetchItems(page); };
    window.addEventListener('movie-updated', onUpdate);
    window.addEventListener('cyber:job:finished', onUpdate);
    return () => {
      window.removeEventListener('movie-updated', onUpdate);
      window.removeEventListener('cyber:job:finished', onUpdate);
    };
  }, [page, issueCode, liveCheck]);

  const toggleSelect = (key: string) => {
    setSelectedKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const togglePageSelect = () => {
    setSelectedKeys(prev => {
      const allKeys = items.map((it, idx) => itemKeyOf(it, idx)).filter(k => !k.startsWith('__'));
      const allSelected = allKeys.length > 0 && allKeys.every(k => prev.has(k));
      if (allSelected) {
        const next = new Set(prev);
        allKeys.forEach(k => next.delete(k));
        return next;
      }
      const next = new Set(prev);
      allKeys.forEach(k => next.add(k));
      return next;
    });
  };

  const allSelectableKeys = useMemo(() =>
    items.map((it, idx) => itemKeyOf(it, idx)).filter(k => !k.startsWith('__')),
    [items]
  );
  const allSelected = allSelectableKeys.length > 0 && allSelectableKeys.every(k => selectedKeys.has(k));

  // 生成 plan：可以是单条或批量。拿到后弹确认；用户确认才真的 execute。
  const planThenConfirm = async (resourceIds: string[], explicitIssueCode?: string) => {
    if (resourceIds.length === 0) return;
    setPlanning(true);
    try {
      const payload = await resourceService.planGovernanceCleanup({
        issue_codes: explicitIssueCode ? [explicitIssueCode] : (issueCode !== 'all' ? [issueCode] : undefined),
        resource_ids: resourceIds,
        include_live_check: liveCheck,
      });
      const apply = payload?.apply_payload;
      const planItems = apply?.items || [];
      if (planItems.length === 0) {
        toast.error('没有可执行的清理动作');
        return;
      }
      setPendingPlan({ apply, count: planItems.length });
    } catch (e: any) {
      toast.error(e?.message || '生成清理计划失败');
    } finally {
      setPlanning(false);
    }
  };

  const planAllSelected = () => {
    const ids: string[] = [];
    selectedKeys.forEach(k => {
      const it = items.find((row, idx) => itemKeyOf(row, idx) === k);
      if (it) ids.push(...itemResourceIds(it));
    });
    planThenConfirm(ids);
  };

  const executePendingPlan = async () => {
    if (!pendingPlan?.apply) return;
    setExecuting(true);
    try {
      const job = await resourceService.startGovernanceCleanupJob({
        apply_payload: pendingPlan.apply,
        confirm: true,
      });
      const jobAny = job as any;
      const jobId = jobAny?.job?.id || jobAny?.id;
      if (jobId) {
        toast.success(`已提交 ${pendingPlan.count} 项清理任务`);
        window.dispatchEvent(new CustomEvent('cyber:job:started', {
          detail: { jobId, label: `资源治理清理 (${pendingPlan.count} 项)` },
        }));
        setSelectedKeys(new Set());
        setPendingPlan(null);
      } else {
        toast.error('提交清理任务失败');
      }
    } catch (e: any) {
      toast.error(e?.message || '执行清理失败');
    } finally {
      setExecuting(false);
    }
  };

  const issueLabel = (code: string): string => {
    const t = taxonomy?.resource_governance_issue_codes?.find((c: any) => c.code === code);
    return t?.label || t?.label_en || code;
  };

  const visibleStatCodes: any[] = taxonomy?.resource_governance_issue_codes?.filter((issue: any) => {
    const count = summary?.totals?.[issue.code] || 0;
    return count > 0 || issue.severity === 'high';
  }) || [];

  return (
    <div className="flex flex-col gap-6 text-white font-mono">
      {/* Stat 卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
        {visibleStatCodes.length > 0 ? visibleStatCodes.map((issue: any) => {
          const count = summary?.totals?.[issue.code] || 0;
          const isHigh = issue.severity === 'high';
          return (
            <div
              key={issue.code}
              className={`p-4 border ${count > 0 ? (isHigh ? 'border-red-500/30 bg-red-500/5' : 'border-yellow-500/30 bg-yellow-500/5') : 'border-primary-30 bg-primary-5'}`}
            >
              <div className="text-[10px] text-primary-50 mb-1 uppercase break-words">{issueLabel(issue.code)}</div>
              <div className={`text-2xl font-bold ${count > 0 ? (isHigh ? 'text-red-400' : 'text-yellow-400') : 'text-primary'}`}>
                {count}
              </div>
            </div>
          );
        }) : (
          <div className="col-span-full p-4 border border-primary-30 bg-primary-5 text-primary-50 text-xs">
            暂未发现资源问题
          </div>
        )}
      </div>

      {/* 工具栏：过滤 + 存活检测 + 批量执行 */}
      <div className="flex flex-col md:flex-row md:justify-between md:items-center gap-3 bg-[#0a0a12] border border-primary-30 p-4">
        <div className="flex flex-wrap gap-4 items-center">
          <div className="flex gap-2 items-center">
            <span className="text-xs text-primary-50">问题过滤</span>
            <select
              value={issueCode}
              onChange={e => setIssueCode(e.target.value)}
              className="bg-black border border-primary-30 px-2 py-1 text-primary text-sm"
            >
              <option value="all">全部</option>
              {taxonomy?.resource_governance_issue_codes?.map((issue: any) => (
                <option key={issue.code} value={issue.code}>{issue.label || issue.label_en || issue.code}</option>
              )) || (
                <>
                  <option value="invalid_path">路径失效</option>
                  <option value="detached_source_resource">孤立资源</option>
                  <option value="duplicate_playback_resource">重复资源</option>
                </>
              )}
            </select>
          </div>
          <label className="flex gap-2 items-center text-xs text-primary-50 cursor-pointer">
            <input
              type="checkbox"
              checked={liveCheck}
              onChange={e => setLiveCheck(e.target.checked)}
              className="accent-primary"
            />
            <span>存活检测</span>
            <span className="text-primary-50/60 text-[10px]">(逐个回源 stat，会拖慢加载)</span>
          </label>
        </div>
        <div className="flex gap-2 items-center">
          {selectedKeys.size > 0 && (
            <button
              onClick={planAllSelected}
              disabled={planning}
              className="flex gap-2 items-center px-4 py-2 bg-red-500 text-white hover:bg-red-600 transition-colors disabled:opacity-50"
            >
              {planning ? <Loader2 className="animate-spin w-4 h-4" /> : <Trash2 className="w-4 h-4" />}
              <span className="text-sm tracking-widest uppercase">清理选中 ({selectedKeys.size})</span>
            </button>
          )}
        </div>
      </div>

      {/* 列表 */}
      <div className="border border-primary-30 bg-[#0a0a12] p-4 text-sm overflow-x-auto min-h-[400px]">
        {loading ? (
          <div className="flex justify-center items-center h-48"><Loader2 className="animate-spin text-primary w-8 h-8" /></div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-primary-30/50 text-primary-50 text-xs uppercase tracking-widest">
                <th className="py-3 px-2 w-10">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={togglePageSelect}
                    disabled={allSelectableKeys.length === 0}
                    className="accent-primary cursor-pointer disabled:cursor-not-allowed"
                    title={allSelected ? '取消全选当前页' : '全选当前页'}
                  />
                </th>
                {issueCode === 'all' && <th className="py-3 px-2 w-32">问题</th>}
                <th className="py-3 px-2">资源与路径</th>
                <th className="py-3 px-2 w-1/3">信息 / 建议</th>
                <th className="py-3 px-2 w-24 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => {
                const key = itemKeyOf(item, idx);
                const ids = itemResourceIds(item);
                const checked = selectedKeys.has(key);
                const path = item.path_check?.path || (item.resource as any)?.path || item.path || 'UNKNOWN';
                const src = item.source || (item.resource as any)?.source;

                return (
                  <tr key={key} className="border-b border-primary-30/20 hover:bg-primary-5 transition-colors">
                    <td className="py-3 px-2 align-top">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSelect(key)}
                        disabled={ids.length === 0}
                        className="accent-primary cursor-pointer disabled:cursor-not-allowed"
                        title={ids.length === 0 ? '该项缺少 resource_id，无法清理' : undefined}
                      />
                    </td>
                    {issueCode === 'all' && (
                      <td className="py-3 px-2 align-top">
                        <span
                          className={`inline-block px-2 py-1 text-[10px] whitespace-nowrap ${item.issue_code === 'invalid_path' ? 'bg-red-500/20 text-red-500 border border-red-500/30' : 'bg-primary-20 text-primary border border-primary-30'}`}
                        >
                          {issueLabel(item.issue_code)}
                        </span>
                      </td>
                    )}
                    <td className="py-3 px-2 font-mono text-xs align-top pt-4">
                      {item.movie_title && <div className="text-white font-bold mb-2 text-sm">{item.movie_title}</div>}
                      {item.resources ? (
                        <div className="flex flex-col gap-2">
                          {item.resources.map((r: any) => (
                            <div key={r.resource_id} className="p-2 border border-primary-30 bg-black flex flex-col gap-1 rounded-sm">
                              <div className="flex justify-between items-start gap-4">
                                <span className="text-[10px] text-primary-50 break-all">{r.resource_id}</span>
                                <span className="text-[10px] bg-primary-20 px-1 text-primary whitespace-nowrap">{r.source?.name || 'UNKNOWN'}</span>
                              </div>
                              <div className="text-primary-70 text-[11px] break-all">{r.path}</div>
                              {r.size_bytes !== undefined && <div className="text-primary-50 text-[10px]">{(r.size_bytes / 1024 / 1024 / 1024).toFixed(2)} GB</div>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="p-2 border border-primary-30 bg-black flex flex-col gap-1 rounded-sm">
                          <div className="flex justify-between items-start gap-4">
                            <div className="flex flex-col">
                              {ids.map(id => <span key={id} className="text-[10px] text-primary-50 break-all">{id}</span>)}
                            </div>
                            <span className="text-[10px] bg-primary-20 px-1 text-primary whitespace-nowrap">{src?.name || src?.source_id || 'UNKNOWN'}</span>
                          </div>
                          <div className="text-primary-70 text-[11px] break-all">{path}</div>
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-2 font-mono text-xs text-primary-50 align-top pt-4">
                      <div className="leading-relaxed text-primary-70">
                        {item.recommendation || item.message || item.info || ''}
                      </div>
                      {item.duplicate_key && (
                        <div className="p-2 bg-primary-5 border border-primary-30 mt-2 text-[10px] flex flex-col gap-1 rounded-sm">
                          <div><span className="text-primary">文件名:</span> <span className="break-all">{item.duplicate_key.filename}</span></div>
                          {item.duplicate_key.season != null && <div><span className="text-primary">第:</span> {item.duplicate_key.season} 季</div>}
                          {item.duplicate_key.episode != null && <div><span className="text-primary">集:</span> {item.duplicate_key.episode}</div>}
                          {item.duplicate_key.size_bytes != null && (
                            <div><span className="text-primary">尺寸:</span> {(item.duplicate_key.size_bytes / 1024 / 1024 / 1024).toFixed(2)} GB</div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-2 align-top text-right pt-4">
                      <button
                        onClick={() => planThenConfirm(ids, item.issue_code)}
                        disabled={ids.length === 0 || planning}
                        className="px-3 py-1 border border-red-500/40 text-red-400 hover:bg-red-500 hover:text-white text-[10px] uppercase tracking-wider transition-colors rounded-sm disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-red-400"
                      >
                        清理
                      </button>
                    </td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={issueCode === 'all' ? 5 : 4} className="py-8 text-center text-primary-50">暂无需治理的资源</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* 分页 */}
      <div className="flex justify-between items-center mt-4">
        <span className="text-primary-50 tracking-widest text-sm flex items-center gap-4">
          当前页 {page} / 总页数 {totalPages}
          <span className="flex items-center gap-2">
            前往 <input
              type="number"
              min={1}
              max={totalPages || 1}
              className="w-16 bg-black/40 border border-primary-30 text-primary text-center py-1 focus:border-primary focus:outline-none transition-colors"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const p = parseInt(e.currentTarget.value);
                  if (p > 0 && p <= totalPages) setPage(p);
                }
              }}
              placeholder={String(page)}
            /> 页
          </span>
        </span>
        <div className="flex gap-2">
          <button
            disabled={page === 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
            className="px-4 py-1 border border-primary-30 text-primary disabled:opacity-30 disabled:cursor-not-allowed hover:bg-primary hover:text-black transition-colors"
          >
            上一页
          </button>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => p + 1)}
            className="px-4 py-1 border border-primary-30 text-primary disabled:opacity-30 disabled:cursor-not-allowed hover:bg-primary hover:text-black transition-colors"
          >
            下一页
          </button>
        </div>
      </div>

      {/* 清理确认弹窗 */}
      {pendingPlan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={() => !executing && setPendingPlan(null)}
          />
          <div className="relative bg-[#0a0a12] border border-red-500/30 rounded-2xl w-full max-w-md p-6 md:p-8 shadow-[0_0_50px_rgba(239,68,68,0.15)] animate-in zoom-in-95 duration-200 border-t-2 border-t-red-500/50">
            <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-3">
              <Trash2 className="text-red-500" size={20} />
              确认清理
            </h3>
            <p className="text-gray-300 mt-3 text-sm">
              即将清理 <span className="text-red-400 font-bold">{pendingPlan.count}</span> 条资源记录。
            </p>
            <p className="text-[11px] text-gray-500 mt-2 leading-relaxed">
              仅删除数据库索引（含历史 / 字幕引用）；不会动云盘 / 本地的物理文件。
              如果误删可在后端日志找到 restore snapshot 救回。
            </p>
            <div className="mt-6 flex gap-4">
              <button
                disabled={executing}
                onClick={() => setPendingPlan(null)}
                className="px-5 py-2.5 rounded-lg border border-white/10 text-gray-400 hover:bg-white/5 text-sm tracking-wider flex-1 transition-all disabled:opacity-50"
              >
                取消
              </button>
              <button
                disabled={executing}
                onClick={executePendingPlan}
                className="px-5 py-2.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-500 hover:bg-red-500 hover:text-black text-sm tracking-wider flex-1 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {executing && <Loader2 className="w-4 h-4 animate-spin" />}
                确认清理
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
