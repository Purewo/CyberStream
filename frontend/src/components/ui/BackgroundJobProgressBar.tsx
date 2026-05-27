import React, { useEffect, useRef, useState } from 'react';
import { Activity, CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react';
import { systemService } from '../../api';

// 通用 background job 进度条 —— 跟扫描状态条 (ScanProgressBar) 平级，
// 监听全局事件 `cyber:job:started`，订阅 GET /v1/jobs/{job_id} 直到任务终态
// (succeeded / failed)。卡片右下角，跟扫描条同位置；如果两者同时活动会
// 互相挡，但实践上扫描和重刮不会并发，先不做堆叠。
//
// payload 形如：
//   window.dispatchEvent(new CustomEvent('cyber:job:started', {
//     detail: { jobId, label?: '批量重刮元数据' }
//   }))

type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

interface JobSnapshot {
  id: string;
  label: string;
  status: JobStatus;
  current: number;
  total: number;
  message: string;
  errorMessage?: string;
}

const POLL_INTERVAL_MS = 1500;
// 终态后保留多少 ms 让用户看清结果
const HOLD_FINAL_MS = 4000;

export const BackgroundJobProgressBar: React.FC = () => {
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const timerRef = useRef<number | null>(null);
  const dismissTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const stopPolling = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const scheduleDismiss = () => {
      if (dismissTimerRef.current !== null) window.clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = window.setTimeout(() => {
        setJob(null);
        dismissTimerRef.current = null;
      }, HOLD_FINAL_MS);
    };

    const pollOnce = async (jobId: string, label: string) => {
      try {
        const raw = await systemService.getJob(jobId);
        const data: any = raw?.data ?? raw;
        if (!data) {
          // 拉不到（404 / 后端重启），就认为失败收掉
          setJob(prev => prev && prev.id === jobId ? { ...prev, status: 'failed', errorMessage: '任务状态丢失' } : prev);
          scheduleDismiss();
          return;
        }
        const status: JobStatus = data.status || 'running';
        const progress = data.progress || {};
        const errorMessage = data.error?.message;
        setJob({
          id: jobId,
          label,
          status,
          current: progress.current ?? 0,
          total: progress.total ?? 0,
          message: progress.message ?? '',
          errorMessage,
        });
        if (status === 'succeeded' || status === 'failed') {
          stopPolling();
          scheduleDismiss();
          window.dispatchEvent(new CustomEvent('cyber:job:finished', {
            detail: { jobId, status, errorMessage },
          }));
          return;
        }
        timerRef.current = window.setTimeout(() => pollOnce(jobId, label), POLL_INTERVAL_MS);
      } catch (e) {
        console.warn('[BackgroundJobProgressBar] poll failed', e);
        timerRef.current = window.setTimeout(() => pollOnce(jobId, label), POLL_INTERVAL_MS);
      }
    };

    const handleStarted = (e: Event) => {
      const detail = (e as CustomEvent<{ jobId?: string; label?: string }>).detail;
      if (!detail?.jobId) return;
      stopPolling();
      if (dismissTimerRef.current !== null) {
        window.clearTimeout(dismissTimerRef.current);
        dismissTimerRef.current = null;
      }
      const label = detail.label || '后台任务';
      setJob({
        id: detail.jobId,
        label,
        status: 'queued',
        current: 0,
        total: 0,
        message: '排队中',
      });
      pollOnce(detail.jobId, label);
    };

    window.addEventListener('cyber:job:started', handleStarted);
    return () => {
      window.removeEventListener('cyber:job:started', handleStarted);
      stopPolling();
      if (dismissTimerRef.current !== null) window.clearTimeout(dismissTimerRef.current);
    };
  }, []);

  if (!job) return null;

  const isFinal = job.status === 'succeeded' || job.status === 'failed';
  const percent = job.total > 0
    ? Math.min(100, Math.round((job.current / job.total) * 100))
    : (job.status === 'succeeded' ? 100 : 0);
  const isIndeterminate = !isFinal && (job.total === 0 || job.status === 'queued');

  const statusIcon = (() => {
    switch (job.status) {
      case 'succeeded': return <CheckCircle2 size={14} className="text-green-400" />;
      case 'failed': return <AlertCircle size={14} className="text-red-400" />;
      case 'queued': return <Loader2 size={14} className="text-yellow-400 animate-spin" />;
      default: return <Activity size={14} className="text-cyan-400" />;
    }
  })();

  const statusLabel = (() => {
    switch (job.status) {
      case 'succeeded': return '已完成';
      case 'failed': return '失败';
      case 'queued': return '排队中';
      default: return '进行中';
    }
  })();

  const accentClass = job.status === 'failed'
    ? 'text-red-400'
    : job.status === 'succeeded'
      ? 'text-green-400'
      : 'text-primary';

  const barClass = job.status === 'failed'
    ? 'bg-red-500'
    : job.status === 'succeeded'
      ? 'bg-green-400'
      : 'bg-primary';

  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 bg-[#0a0a0a]/90 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl p-4 overflow-hidden animate-in slide-in-from-bottom-5 fade-in duration-300">
      <div className="absolute inset-0 bg-[linear-gradient(transparent_50%,rgba(0,0,0,0.1)_50%)] bg-[length:100%_4px] pointer-events-none opacity-20"></div>
      <div className="flex items-center justify-between mb-3 relative z-10">
        <div className="flex items-center gap-2">
          <div className="relative">
            {!isFinal && job.status !== 'queued' && (
              <div className="absolute inset-0 bg-primary/30 rounded-full animate-ping"></div>
            )}
            <div className="w-6 h-6 rounded-full bg-white/5 border border-white/10 flex items-center justify-center relative z-10">
              {statusIcon}
            </div>
          </div>
          <div>
            <h4 className="text-xs font-bold text-gray-200">{job.label}</h4>
            <p className="text-[10px] text-gray-400 font-['Rajdhani'] uppercase tracking-widest">{statusLabel}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`text-sm font-black font-['Rajdhani'] ${accentClass}`}>
            {isIndeterminate ? (
              <span className="flex items-center gap-1"><span className="animate-pulse">_</span>SYNC</span>
            ) : (
              `${percent}%`
            )}
          </div>
          {isFinal && (
            <button
              onClick={() => setJob(null)}
              className="text-gray-500 hover:text-white p-1 rounded transition-colors"
              title="关闭"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>
      <div className="relative z-10 mb-2">
        <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden flex items-stretch">
          {isIndeterminate ? (
            <div className={`h-full w-1/3 ${barClass} rounded-full animate-[progressIndeterminate_1.5s_infinite_ease-in-out]`}></div>
          ) : (
            <div
              className={`h-full ${barClass} rounded-full transition-all duration-300 relative`}
              style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
            >
              <div className="absolute inset-0 bg-gradient-to-r from-black/50 to-transparent"></div>
            </div>
          )}
        </div>
      </div>
      <div className="space-y-1 relative z-10">
        <div className="flex justify-between text-[11px] gap-2">
          <span className="text-gray-400 truncate flex-1">
            {job.errorMessage || job.message || (isFinal ? '操作完成' : '正在初始化...')}
          </span>
          {job.total > 0 && (
            <span className="text-gray-500 font-['Rajdhani'] whitespace-nowrap">
              {job.current} / {job.total}
            </span>
          )}
        </div>
      </div>
      <style>{`
        @keyframes progressIndeterminate {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(300%); }
        }
      `}</style>
    </div>
  );
};
