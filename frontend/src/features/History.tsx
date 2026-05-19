import React, { useMemo, useState } from 'react';
import { Brain, Trash2, Layers, Clock, Activity, Database, Film, Play, X, AlertTriangle } from 'lucide-react';
import { Movie, HistoryItem } from '../types';
import { CyberSword, SciFiProgressRing, SciFiProgressBar } from '../components/ui/CyberComponents';
import { formatDuration } from '../utils';

export const HistoryPage = ({ history, onMovieSelect, onClearHistory, onDeleteHistoryItem }: { history: HistoryItem[]; onMovieSelect: (m: Movie) => void; onClearHistory: () => void; onDeleteHistoryItem: (id: string) => void }) => {
  const [confirmClear, setConfirmClear] = useState(false);

  // Group history items by date
  const groupedHistory = useMemo(() => {
    if (!history || !Array.isArray(history)) return [];
    
    const groups: Record<string, HistoryItem[]> = {};
    history.forEach(item => {
      // Use date string as key, default to "Recent" if missing
      const dateKey = item.date || "RECENT";
      if (!groups[dateKey]) {
        groups[dateKey] = [];
      }
      groups[dateKey].push(item);
    });

    return Object.entries(groups).map(([date, items]) => ({ date, items }));
  }, [history]);

  // Calculate stats
  const totalItems = history ? history.length : 0;
  let totalDuration = 0;
  let totalProgress = 0;
  
  if (history && Array.isArray(history)) {
    history.forEach((item) => {
      totalDuration += (item.duration || 0);
      totalProgress += (item.progress || 0);
    });
  }
  
  const completionRate = totalDuration > 0 ? Math.round((totalProgress / totalDuration) * 100) : 0;

  return (
    <div className="min-h-screen w-full pt-24 px-4 md:px-12 pb-12">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6 mb-12 border-b border-white/10 pb-6">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <Brain className="text-primary" size={24} />
            <h2 className="text-sm font-['Orbitron'] text-primary tracking-[0.2em]">NEURAL_ARCHIVE</h2>
          </div>
          <h1 className="text-4xl font-['Noto_Sans_SC'] font-bold text-white glitch-text" data-text="观看记录">观看记录</h1>
        </div>
        
        {confirmClear ? (
          <div className="flex items-center gap-2 animate-in slide-in-from-right-4">
             <span className="text-xs text-red-500 font-bold font-['Orbitron'] flex items-center gap-1"><AlertTriangle size={14} /> CONFIRM DELETE ALL?</span>
             <button onClick={() => { onClearHistory(); setConfirmClear(false); }} className="px-4 py-2 bg-red-500 text-black font-bold text-xs hover:bg-white transition-colors">YES, WIPE</button>
             <button onClick={() => setConfirmClear(false)} className="px-4 py-2 border border-white/20 text-gray-400 font-bold text-xs hover:text-white transition-colors">CANCEL</button>
          </div>
        ) : (
          <button onClick={() => setConfirmClear(true)} className="flex items-center gap-2 px-4 py-2 border border-red-500/50 text-red-500 hover:bg-red-500 hover:text-black transition-all font-['Orbitron'] text-xs font-bold">
            <Trash2 size={14} /> WIPE_MEMORY
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
        <div className="bg-[#0a0a12]/60 border border-white/10 p-6 relative overflow-hidden group hover:border-primary/50 transition-colors">
          <div className="absolute top-0 right-0 p-4 text-primary group-hover:opacity-100 transition-all duration-500 drop-shadow-[0_0_10px_var(--color-primary)] animate-pulse"><Layers size={48} /></div>
          <div className="text-xs text-primary font-['Orbitron'] mb-2">TOTAL_ARCHIVES</div>
          <div className="text-3xl font-['Rajdhani'] font-bold text-white group-hover:text-primary transition-colors">{totalItems}</div>
        </div>
        <div className="bg-[#0a0a12]/60 border border-white/10 p-6 relative overflow-hidden group hover:border-secondary/50 transition-colors">
          <div className="absolute top-0 right-0 p-4 text-secondary group-hover:opacity-100 transition-all duration-500 drop-shadow-[0_0_10px_var(--color-secondary)] animate-pulse"><Clock size={48} /></div>
          <div className="text-xs text-secondary font-['Orbitron'] mb-2">SYNC_DURATION</div>
          <div className="text-3xl font-['Rajdhani'] font-bold text-white group-hover:text-secondary transition-colors">{formatDuration(totalProgress)}</div>
        </div>
        <div className="bg-[#0a0a12]/60 border border-white/10 p-6 relative overflow-hidden group hover:border-accent/50 transition-colors">
          <div className="absolute top-0 right-0 p-4 text-accent group-hover:opacity-100 transition-all duration-500 drop-shadow-[0_0_10px_var(--color-accent)] animate-pulse"><Activity size={48} /></div>
          <div className="text-xs text-accent font-['Orbitron'] mb-2">SYNC_RATE</div>
          <div className="text-3xl font-['Rajdhani'] font-bold text-white group-hover:text-accent transition-colors">{completionRate}%</div>
          <div className="w-full h-1 bg-gray-800 mt-2 rounded-full overflow-hidden">
             <div className="h-full bg-accent" style={{ width: `${completionRate}%` }}></div>
          </div>
        </div>
      </div>
      
      <div className="mb-12 hidden md:block">
         <CyberSword />
      </div>

      {groupedHistory.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-gray-500">
          <Database size={48} className="mb-4 opacity-20" />
          <div className="font-['Orbitron'] tracking-widest">MEMORY_BANKS_EMPTY</div>
        </div>
      ) : (
        <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-500">
          {groupedHistory.map((group, idx) => (
            <div key={idx}>
              <h3 className="text-xl font-['Orbitron'] font-bold text-white mb-6 flex items-center gap-2">
                 <span className="w-2 h-2 bg-primary rounded-full"></span>
                 {group.date}
              </h3>
              <div className="grid grid-cols-1 gap-4">
                {group.items.map((item: HistoryItem & { resourceId?: string }) => {
                   // Calculate percentage, guard against 0 duration
                   const pct = item.duration > 0 ? Math.min(100, Math.round((item.progress / item.duration) * 100)) : 0;
                   return (
                    <div key={item.id || Math.random()} className="group bg-[#0a0a12]/40 border border-white/10 hover:border-primary/50 transition-all p-4 flex flex-col md:flex-row items-center gap-6 cursor-pointer relative overflow-hidden hover:bg-white/5 shadow-[0_0_20px_rgba(0,0,0,0.3)] hover:shadow-[0_0_20px_rgba(0,243,255,0.1)]" onClick={() => onMovieSelect(item)}>
                      {item.resourceId && (
                        <button 
                          onClick={(e) => { e.stopPropagation(); onDeleteHistoryItem(item.resourceId!); }}
                          className="absolute top-2 right-2 p-2 text-gray-600 hover:text-red-500 hover:bg-red-500/10 rounded-full z-20 transition-all opacity-0 group-hover:opacity-100"
                          title="Delete Record"
                        >
                          <X size={16} />
                        </button>
                      )}
                      
                      <div className="w-full md:w-48 h-28 shrink-0 relative overflow-hidden border border-white/10 group-hover:border-primary/50 transition-colors">
                         {item.cover_url ? (
                            <img src={item.cover_url} alt={item.title} referrerPolicy="no-referrer" className="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" />
                         ) : (
                            <div className="absolute inset-0 bg-gray-800 flex items-center justify-center"><Film className="text-gray-600" /></div>
                         )}
                         <div className="absolute inset-0 bg-black/20 group-hover:bg-transparent transition-colors"></div>
                         <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                             <div className="bg-black/60 p-2 rounded-full border border-primary text-primary backdrop-blur-sm"><Play size={20} fill="currentColor" /></div>
                         </div>
                      </div>
                      
                      <div className="flex-1 w-full">
                         <div className="flex justify-between items-start mb-2">
                            <div className="pr-8">
                               <h4 className="text-lg font-bold text-white font-['Noto_Sans_SC'] group-hover:text-primary transition-colors truncate">
                                  {item.title}
                                  {item.target_season !== undefined ? ` 第${item.target_season}季` : ''}
                                  {item.user_data?.episode_label ? ` ${item.user_data.episode_label}` : (item.user_data?.episode !== undefined ? ` 第${item.user_data.episode}集` : '')}
                               </h4>
                               <div className="text-xs text-gray-500 font-['Rajdhani'] flex items-center gap-2 mt-1">
                                  <Clock size={12} className="text-gray-500" />
                                  <span>{item.time_str}</span>
                                  <span className="w-1 h-1 bg-gray-600 rounded-full"></span>
                                  <span className="text-gray-400">{formatDuration(item.progress)} / {formatDuration(item.duration)}</span>
                               </div>
                            </div>
                            <SciFiProgressRing progress={pct} size={40} />
                         </div>
                         
                         <SciFiProgressBar progress={pct} />
                      </div>
                    </div>
                   );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};