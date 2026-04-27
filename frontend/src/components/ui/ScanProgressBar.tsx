import React, { useEffect, useState } from 'react';
import { systemService } from '../../api';
import { ScanStatus } from '../../types';
import { Activity, Database, AlertCircle, FileText, CheckCircle2 } from 'lucide-react';

export const ScanProgressBar = () => {
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [isVisible, setIsVisible] = useState(false);
  const wasScanning = React.useRef(false);

  useEffect(() => {
    let intervalId: number | null = null;

    const stopPolling = () => {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };

    const startPolling = () => {
      if (!intervalId) {
        intervalId = setInterval(checkStatus, 1500) as unknown as number;
      }
    };

    const checkStatus = async () => {
      try {
        const status = await systemService.getScanStatus();
        console.log('Scan status polling:', status);
        setScanStatus(status);
        
        // Support both old backend (status) and new backend (state)
        const currentState = (status as any)?.state || (status as any)?.status;
        const isCurrentlyScanning = currentState === 'scanning' || currentState === 'stopping';
        
        if (isCurrentlyScanning) {
          setIsVisible(true);
          wasScanning.current = true;
          startPolling(); // Ensure polling is active
          window.dispatchEvent(new CustomEvent('cyber:scan:updated'));
        } else if (currentState === 'idle') {
          console.log('Scan status is idle');
          
          // Stop everything immediately if idle
          stopPolling();

          // If we were scanning and just finished
          if (wasScanning.current) {
            window.dispatchEvent(new CustomEvent('cyber:scan:completed'));
            wasScanning.current = false;
            // Delay hiding to allow user to see 100% completion state
            setTimeout(() => setIsVisible(false), 3000);
          } else {
            // Already idle or not scanning, ensure it is hidden
            setIsVisible(false);
          }
        } else {
           console.log('Scan status is unknown or undefined');
           setIsVisible(false);
           wasScanning.current = false;
           stopPolling();
        }
      } catch (e) {
        console.error('Failed to get scan status', e);
        stopPolling(); // Stop on error to be safe
      }
    };

    // Global event listener to wake up the seeker when a scan is manually started
    const handleScanStarted = () => {
      setIsVisible(true);
      checkStatus(); // This will trigger startPolling() inside
    };
    window.addEventListener('cyber:scan:started', handleScanStarted);

    // One-time check on mount
    checkStatus();

    return () => {
      stopPolling();
      window.removeEventListener('cyber:scan:started', handleScanStarted);
    };
  }, []);

  if (!isVisible || !scanStatus) return null;

  const currentState = scanStatus.state || (scanStatus as any).status;
  const currentFile = scanStatus.current_file || (scanStatus as any).current_item;
  const progressPercent = scanStatus.progress ?? 0;
  
  let progressText = '扫描中...';
  if (scanStatus.speed) progressText = scanStatus.speed;
  if (scanStatus.remaining_time) progressText += ` | 剩余时间: ${scanStatus.remaining_time}`;
  
  if (currentState === 'idle') {
      progressText = '操作完成';
  } else if (currentState === 'stopping') {
      progressText = '正在停止扫描...';
  }

  const isIndeterminate = progressPercent <= 0 && currentState !== 'idle';


  const getPhaseIcon = () => {
    switch (currentState) {
      case 'idle': return <CheckCircle2 size={14} className="text-green-400" />;
      case 'stopping': return <AlertCircle size={14} className="text-yellow-400" />;
      case 'scanning': return <FileText size={14} className="text-cyan-400" />;
      default: return <Activity size={14} className="text-gray-400" />;
    }
  };

  const getPhaseName = () => {
    switch (currentState) {
      case 'scanning': return '扫描索引';
      case 'stopping': return '正在停止';
      case 'idle': return '已完成';
      default: return '进行中';
    }
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 bg-[#0a0a0a]/90 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl p-4 overflow-hidden animate-in slide-in-from-bottom-5 fade-in duration-300">
       {/* Scanline decoration inside card */}
       <div className="absolute inset-0 bg-[linear-gradient(transparent_50%,rgba(0,0,0,0.1)_50%)] bg-[length:100%_4px] pointer-events-none opacity-20"></div>

       <div className="flex items-center justify-between mb-3 relative z-10">
          <div className="flex items-center gap-2">
             <div className="relative">
                {currentState === 'scanning' && <div className="absolute inset-0 bg-primary/30 rounded-full animate-ping"></div>}
                <div className="w-6 h-6 rounded-full bg-white/5 border border-white/10 flex items-center justify-center relative z-10">
                   {getPhaseIcon()}
                </div>
             </div>
             <div>
               <h4 className="text-xs font-bold text-gray-200">库资源扫描</h4>
               <p className="text-[10px] text-gray-400 flex items-center gap-1 font-['Rajdhani'] uppercase tracking-widest">{getPhaseName()}</p>
             </div>
          </div>
          <div className="text-right">
             <div className="text-sm font-black text-primary font-['Rajdhani']">
               {isIndeterminate ? (
                   <span className="flex items-center gap-1"><span className="animate-pulse">_</span>SYNC</span>
               ) : (
                   `${currentState === 'idle' ? 100 : Math.round(progressPercent)}%`
               )}
             </div>
          </div>
       </div>

       <div className="relative z-10 mb-2">
           <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden flex items-stretch">
               {isIndeterminate ? (
                   <div className="h-full w-1/3 bg-primary rounded-full animate-[progressIndeterminate_1.5s_infinite_ease-in-out]" style={{ boxShadow: '0 0 10px var(--color-primary)' }}></div>
               ) : (
                   <div 
                      className="h-full bg-primary rounded-full transition-all duration-300 relative"
                      style={{ 
                          width: `${Math.max(0, Math.min(100, currentState === 'idle' ? 100 : progressPercent))}%`,
                          boxShadow: '0 0 10px var(--color-primary)'
                      }}
                   >
                     <div className="absolute inset-0 bg-gradient-to-r from-black/50 to-transparent"></div>
                   </div>
               )}
           </div>
       </div>

       <div className="space-y-1 relative z-10">
         <div className="flex justify-between text-[11px]">
            <span className="text-gray-400 truncate pr-2 flex-1">{currentFile || '正在初始化...'}</span>
            <span className="text-gray-500 font-['Rajdhani'] whitespace-nowrap overflow-hidden text-ellipsis ml-2 max-w-[150px] text-right">{progressText}</span>
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
