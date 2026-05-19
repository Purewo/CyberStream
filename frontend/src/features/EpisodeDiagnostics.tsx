import React, { useState, useEffect } from 'react';
import { ShieldAlert, CheckCircle, Database, Server, Loader2, Play, FileJson } from 'lucide-react';
import { movieService, systemService } from '../api';
import { MovieCard } from '../components/movies/Cards';

export const EpisodeDiagnostics = ({ taxonomy }: { taxonomy?: any }) => {
  const [summary, setSummary] = useState<any>(null);

  // Helper to safely get counts from issues array
  const getIssueCount = (code: string) => {
      if (!summary?.issues) return 0;
      const issue = summary.issues.find((i: any) => i.code === code);
      return issue?.movie_count || issue?.affected_count || 0;
  };
  const [issueCode, setIssueCode] = useState<string>('all');
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  
  // Jobs
  const [activeJob, setActiveJob] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [planning, setPlanning] = useState(false);

  const fetchSummary = async () => {
    try {
      const data = await movieService.getMetadataQualitySummary();
      setSummary(data);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchItems = async (p = 1) => {
    setLoading(true);
    try {
      const data = await movieService.getEpisodeReviewItems(p, 20, {
        metadata_issue_code: issueCode === 'all' ? undefined : issueCode
      });
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
  }, []);

  useEffect(() => {
    fetchItems(page);
  }, [page, issueCode]);

  useEffect(() => {
    const handleMovieUpdated = () => {
      fetchSummary();
      fetchItems(page);
    };
    window.addEventListener('movie-updated', handleMovieUpdated);
    return () => window.removeEventListener('movie-updated', handleMovieUpdated);
  }, [page, issueCode]);

  const handleGeneratePlan = async () => {
    setPlanning(true);
    try {
      // By default plan batch rescrape for the selected issue, or all episode issues
      const codes = issueCode !== 'all' ? [issueCode] : taxonomy?.metadata_issue_codes?.filter((c: any) => c.bucket === 'episode_review').map((c: any) => c.code) || ["season_metadata_missing", "episode_number_missing", "duplicate_episode_numbers", "missing_episode_numbers", "episode_count_mismatch"];
      const payload = await movieService.planBatchReScrapeMetadata({ 
         issue_codes: codes
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
      const job = await movieService.startBatchReScrapeMetadataJob({
        apply_payload: plan.apply_payload
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
        {taxonomy?.metadata_issue_codes?.filter((c: any) => c.bucket === 'episode_review').map((issue: any) => {
           const count = getIssueCount(issue.code);
           if (count === 0 && issue.severity !== 'high') return null; // hide 0 unless high severity
           return (
             <div key={issue.code} className={`p-4 border ${count > 0 ? (issue.severity === 'high' ? 'border-red-500/30 bg-red-500/5' : 'border-yellow-500/30 bg-yellow-500/5') : 'border-primary-30 bg-primary-5'}`}>
               <div className="text-[10px] text-primary-50 mb-1 uppercase break-words">{issue.label || issue.label_en || issue.code}</div>
               <div className={`text-2xl font-bold ${count > 0 ? (issue.severity === 'high' ? 'text-red-400' : 'text-yellow-400') : 'text-primary'}`}>
                 {count}
               </div>
             </div>
           );
        })}
      </div>

      <div className="flex justify-between items-center bg-[#0a0a12] border border-primary-30 p-4">
        <div className="flex gap-4 items-center">
            <span className="text-primary font-bold uppercase tracking-widest text-sm">审查工作台</span>
            <select value={issueCode} onChange={e => setIssueCode(e.target.value)} className="bg-black border border-primary-30 px-2 py-1 text-primary text-sm ml-4">
              <option value="all">所有问题</option>
              {taxonomy?.metadata_issue_codes?.filter((c: any) => c.bucket === 'episode_review').map((issue: any) => (
                 <option key={issue.code} value={issue.code}>{issue.label || issue.label_en || issue.code}</option>
              ))}
            </select>
        </div>
        <div className="flex gap-2">
          {!plan && (
            <button onClick={handleGeneratePlan} disabled={planning} className="flex gap-2 items-center px-4 py-2 border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-50">
              {planning ? <Loader2 className="animate-spin w-4 h-4" /> : <FileJson className="w-4 h-4" />}
              <span className="text-sm tracking-widest uppercase">生成批量重刮计划</span>
            </button>
          )}
          {plan && (
            <button onClick={handleExecutePlan} className="flex gap-2 items-center px-4 py-2 bg-primary text-black hover:bg-primary-hover transition-colors">
              <Play className="w-4 h-4" />
              <span className="text-sm tracking-widest uppercase">执行计划 ({plan.plan?.target_movies_count || 0} 项)</span>
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        {loading ? (
             <div className="col-span-full flex justify-center items-center h-48"><Loader2 className="animate-spin text-primary w-8 h-8" /></div>
        ) : items.map((item: any) => (
            <div key={item.movie_id} className="relative group border border-primary-30 hover:border-primary transition-colors bg-[#0a0a12]">
                <div className="absolute top-0 right-0 z-10 bg-red-500 text-white text-[10px] px-2 py-1 font-bold">
                    待修复
                </div>
                <MovieCard movie={{ id: item.movie_id, title: item.title || 'Unknown', year: item.year || 0, added_at: '', poster_url: item.poster_url || '' } as any} />
                <div className="p-3">
                   <div className="text-xs text-primary-50 mb-1 break-all flex justify-between">
                       <span>S: {item.season_count || 0}</span>
                       <span>部分修复: {item.auto_update_count || 0}</span>
                   </div>
                   {item.metadata_issues?.length > 0 && (
                      <div className="mt-2 space-y-1">
                          {item.metadata_issues.slice(0, 2).map((issue: any, idx: number) => {
                             const taxonomyIssue = taxonomy?.issue_codes?.find((c: any) => c.code === issue.code);
                             const label = taxonomyIssue?.label || taxonomyIssue?.label_en || issue.label || issue.code;
                             return (
                               <div key={idx} className="text-[10px] bg-red-500/20 text-red-400 px-1 py-0.5 whitespace-nowrap overflow-hidden text-ellipsis text-center" title={label}>
                                  {label}
                               </div>
                             );
                          })}
                      </div>
                   )}
                </div>
            </div>
        ))}
        {!loading && items.length === 0 && (
            <div className="col-span-full py-12 text-center text-primary-50">
                暂无需要复核的项目
            </div>
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
