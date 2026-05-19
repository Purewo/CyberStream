import React, { useState, useEffect } from 'react';
import { AlertTriangle, CheckCircle, Database, Server, Loader2, Play, FileJson, Trash2, RotateCw } from 'lucide-react';
import { resourceService, systemService } from '../api';

export const ResourceGovernance = ({ taxonomy }: { taxonomy?: any }) => {
  const [summary, setSummary] = useState<any>(null);
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [liveCheck, setLiveCheck] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [issueCode, setIssueCode] = useState<string>('all');
  
  // Jobs
  const [activeJob, setActiveJob] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [planning, setPlanning] = useState(false);

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
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSummary();
  }, [liveCheck]);

  useEffect(() => {
    fetchItems(page);
  }, [page, issueCode, liveCheck]);

  useEffect(() => {
    const handleMovieUpdated = () => {
      fetchSummary();
      fetchItems(page);
    };
    window.addEventListener('movie-updated', handleMovieUpdated);
    return () => window.removeEventListener('movie-updated', handleMovieUpdated);
  }, [page, issueCode, liveCheck]);

  const handleGeneratePlan = async () => {
    setPlanning(true);
    try {
      const payload = await resourceService.planGovernanceCleanup({ 
        issue_codes: issueCode !== 'all' ? [issueCode] : undefined,
        include_live_check: liveCheck 
      });
      setPlan(payload);
    } catch (e) {
      console.error(e);
    } finally {
      setPlanning(false);
    }
  };

  const handleExecutePlan = async () => {
    if (!plan?.apply_payload) return;
    try {
      const job = await resourceService.startGovernanceCleanupJob({
        apply_payload: plan.apply_payload,
        confirm: true
      });
      if (job) {
        setActiveJob(job);
        setPlan(null);
        // Start polling
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="flex flex-col gap-6 text-white font-mono">
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
        {taxonomy?.resource_governance_issue_codes ? taxonomy.resource_governance_issue_codes.map((issue: any) => {
           const count = summary?.totals?.[issue.code] || 0;
           if (count === 0 && issue.severity !== 'high') return null;
           return (
             <div key={issue.code} className={`p-4 border ${count > 0 ? (issue.severity === 'high' ? 'border-red-500/30 bg-red-500/5' : 'border-yellow-500/30 bg-yellow-500/5') : 'border-primary-30 bg-primary-5'}`}>
               <div className="text-[10px] text-primary-50 mb-1 uppercase break-words">{issue.label_en || issue.label || issue.code}</div>
               <div className={`text-2xl font-bold ${count > 0 ? (issue.severity === 'high' ? 'text-red-400' : 'text-yellow-400') : 'text-primary'}`}>
                 {count}
               </div>
             </div>
           );
        }) : (
          <>
            <div className="p-4 border border-primary-30 bg-primary-5">
              <div className="text-xs text-primary-50 mb-1 uppercase">DETACHED / ORPHAN</div>
              <div className="text-3xl font-bold">{summary?.totals?.detached_source_resource || 0}</div>
            </div>
            <div className="p-4 border border-primary-30 bg-primary-5">
              <div className="text-xs text-primary-50 mb-1 uppercase">DUPLICATE RESOURCES</div>
              <div className="text-3xl font-bold">{summary?.totals?.duplicate_playback_resource || 0}</div>
            </div>
            <div className="p-4 border border-red-500/30 bg-red-500/5">
              <div className="text-xs text-red-500 mb-1 uppercase">INVALID PATH</div>
              <div className="text-3xl font-bold">{summary?.totals?.invalid_path || 0}</div>
            </div>
          </>
        )}
        <div className="p-4 border border-primary-30 bg-primary-5 flex items-center justify-between">
           <div>
             <div className="text-[10px] text-primary-50 mb-1 uppercase">存活检测</div>
             <div className="text-sm font-bold text-primary">{liveCheck ? '已开启' : '已关闭'}</div>
           </div>
           <button 
             onClick={() => setLiveCheck(!liveCheck)}
             className={`px-3 py-1 border text-xs font-bold ${liveCheck ? 'border-primary bg-primary text-black' : 'border-primary-50 text-primary-50'}`}
           >
             切换
           </button>
        </div>
      </div>

      <div className="flex justify-between items-center bg-[#0a0a12] border border-primary-30 p-4">
        <div className="flex gap-4 items-center">
          <span className="text-xs text-primary-50">问题过滤:</span>
          <select value={issueCode} onChange={e => setIssueCode(e.target.value)} className="bg-black border border-primary-30 px-2 py-1 text-primary text-sm">
            <option value="all">全部</option>
            {taxonomy?.resource_governance_issue_codes ? 
              taxonomy.resource_governance_issue_codes.map((issue: any) => (
                <option key={issue.code} value={issue.code}>{issue.label || issue.label_en || issue.code}</option>
              )) : (
              <>
                <option value="invalid_path">INVALID_PATH</option>
                <option value="detached_source_resource">DETACHED_SOURCE_RESOURCE / ORPHAN</option>
                <option value="duplicate_playback_resource">DUPLICATE_PLAYBACK_RESOURCE</option>
              </>
            )}
          </select>
        </div>
        <div className="flex gap-2">
          {!plan && (
            <button onClick={handleGeneratePlan} disabled={planning} className="flex gap-2 items-center px-4 py-2 border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-50">
              {planning ? <Loader2 className="animate-spin w-4 h-4" /> : <FileJson className="w-4 h-4" />}
              <span className="text-sm tracking-widest uppercase">{planning ? '生成计划中...' : '生成清理计划'}</span>
            </button>
          )}
          {plan && (
            <button onClick={handleExecutePlan} className="flex gap-2 items-center px-4 py-2 bg-red-500 text-white hover:bg-red-600 transition-colors">
              <Trash2 className="w-4 h-4" />
              <span className="text-sm tracking-widest uppercase">执行清理 ({plan.plan?.delete_count || 0} 个文件)</span>
            </button>
          )}
        </div>
      </div>

      <div className="border border-primary-30 bg-[#0a0a12] p-4 text-sm overflow-x-auto min-h-[400px]">
        {loading ? (
           <div className="flex justify-center items-center h-48"><Loader2 className="animate-spin text-primary w-8 h-8" /></div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-primary-30/50 text-primary-50 text-xs uppercase tracking-widest">
                <th className="py-3 px-2 w-32">问题</th>
                <th className="py-3 px-2">资源与路径</th>
                <th className="py-3 px-2 w-1/3">信息 / 建议</th>
                <th className="py-3 px-2 w-24 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item: any, idx: number) => {
                const res = item.resource;
                const src = item.source || res?.source;
                const path = item.path_check?.path || res?.path || item.path || 'UNKNOWN';
                const resourceIdList = item.resource_ids || (res ? [res.resource_id] : []);
                const key = resourceIdList.length > 0 ? resourceIdList.join(',') : idx.toString();
                const issueTaxonomy = taxonomy?.resource_governance_issue_codes?.find((c: any) => c.code === item.issue_code);
                
                return (
                  <tr key={key} className="border-b border-primary-30/20 hover:bg-primary-5 transition-colors">
                    <td className="py-3 px-2 align-top">
                       <span className={`inline-block px-2 py-1 text-[10px] whitespace-nowrap ${item.issue_code === 'invalid_path' ? 'bg-red-500/20 text-red-500 border border-red-500/30' : 'bg-primary-20 text-primary border border-primary-30'}`}>
                          {issueTaxonomy?.label || issueTaxonomy?.label_en || item.label || item.issue_code}
                       </span>
                    </td>
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
                                {resourceIdList.map((id: string) => <span key={id} className="text-[10px] text-primary-50 break-all">{id}</span>)}
                             </div>
                             <span className="text-[10px] bg-primary-20 px-1 text-primary whitespace-nowrap">{src?.name || src?.source_id || 'UNKNOWN'}</span>
                           </div>
                           <div className="text-primary-70 text-[11px] break-all">{path}</div>
                         </div>
                       )}
                    </td>
                    <td className="py-3 px-2 font-mono text-xs text-primary-50 align-top pt-4">
                       <div className="mb-2 leading-relaxed text-primary-70">
                         {item.recommendation || item.message || item.info || ''}
                       </div>
                       {item.duplicate_key && (
                         <div className="p-2 bg-primary-5 border border-primary-30 mt-2 text-[10px] flex flex-col gap-1 rounded-sm">
                           <div><span className="text-primary">文件名:</span> <span className="break-all">{item.duplicate_key.filename}</span></div>
                           {item.duplicate_key.season != null && <div><span className="text-primary">第:</span> {item.duplicate_key.season} 季</div>}
                           {item.duplicate_key.episode != null && <div><span className="text-primary">集:</span> {item.duplicate_key.episode}</div>}
                           <div><span className="text-primary">尺寸:</span> {(item.duplicate_key.size_bytes / 1024 / 1024 / 1024).toFixed(2)} GB</div>
                         </div>
                       )}
                    </td>
                    <td className="py-3 px-2 align-top text-right pt-4">
                       <button 
                         onClick={() => {
                           const ids = item.resource_ids || (res ? [res.resource_id] : item.resource_id ? [item.resource_id] : []);
                           if (ids.length > 0) {
                             setPlanning(true);
                             resourceService.planGovernanceCleanup({ 
                               issue_codes: [item.issue_code],
                               resource_ids: ids
                             })
                               .then(payload => setPlan(payload))
                               .catch(e => console.error(e))
                               .finally(() => setPlanning(false));
                           }
                         }}
                         className="px-3 py-1 border border-primary text-primary hover:bg-primary hover:text-black text-[10px] uppercase tracking-wider transition-colors rounded-sm">
                         {issueTaxonomy?.action?.label || '处理'}
                       </button>
                    </td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-primary-50">暂无需治理的资源</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

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
                                if(p > 0 && p <= totalPages) setPage(p); 
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
    </div>
  );
};
