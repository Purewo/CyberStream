import React, { useState, useEffect, useRef } from 'react';
import { Search, Bell, User, Clock, AlertTriangle, Film, Server, MessageSquare, ChevronLeft, Sparkles, X, Loader2, RefreshCw } from 'lucide-react';
import { ViewState, Notification, ScanStatus } from '../../types';
import { systemService } from '../../api';

interface NavbarProps {
  onNavigate: (view: ViewState) => void;
  currentView: ViewState;
  onSearch: (query: string) => void;
  onProfile: () => void;
  notifications: Notification[];
  isCollapsed?: boolean;
  activeLibraryId?: number | null;
  hideLogo?: boolean;
}

const Navbar: React.FC<NavbarProps> = ({ onNavigate, currentView, onSearch, onProfile, notifications, isCollapsed, activeLibraryId = null, hideLogo = false }) => { 
  const [searchValue, setSearchValue] = useState(''); 
  const [showNotifications, setShowNotifications] = useState(false); 
  const [selectedNote, setSelectedNote] = useState<Notification | null>(null); 
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  
  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && searchValue.trim()) onSearch(searchValue); }; 
  const handleSearchClick = () => { 
    if (!isSearchExpanded) {
      setIsSearchExpanded(true);
      setTimeout(() => searchInputRef.current?.focus(), 50);
    } else if (searchValue.trim()) {
      onSearch(searchValue);
    }
  }; 
  
  useEffect(() => { if (!showNotifications) setTimeout(() => setSelectedNote(null), 200); }, [showNotifications]); 

  // Fetch scan status once on mount
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const status = await systemService.getScanStatus();
        setScanStatus(status);
      } catch (e) {
        // Ignore errors for metadata fetch
      }
    };

    fetchStatus();
  }, []);
  
  const getNotificationIcon = (type: string) => { 
    switch (type) { 
      case 'system': return <AlertTriangle size={14} className="text-accent" />; 
      case 'content': return <Film size={14} className="text-primary" />; 
      case 'maintenance': return <Server size={14} className="text-red-500" />; 
      default: return <MessageSquare size={14} className="text-gray-400" />; 
    } 
  }; 
  
  return (
    <> 
      <nav className={`fixed top-0 right-0 w-full z-40 bg-gradient-to-b from-black/80 to-transparent px-6 py-6 flex items-center justify-between transition-all duration-300 md:w-full`}> 
        <div className="flex items-center gap-8 flex-1"> 
          {!hideLogo && (
            <div className="text-2xl font-['Orbitron'] font-black text-transparent bg-clip-text bg-gradient-to-r from-primary to-secondary glitch-text cursor-pointer drop-shadow-[0_0_8px_rgba(var(--color-primary-rgb),0.5)]" onClick={() => onNavigate('home')} data-text="CYBER">CYBER</div> 
          )}
          
          {/* Scan Pulse Indicator */}
          {(() => {
            const currentState = scanStatus?.state || (scanStatus as any)?.status;
            const isScanning = currentState === 'scanning' || currentState === 'stopping';
            
            if (!isScanning) return null;
            
            return (
              <div className="hidden lg:flex items-center gap-3 px-3 py-1 bg-primary/10 border border-primary/30 rounded-full animate-pulse">
                  <Loader2 size={12} className="text-primary animate-spin" />
                  <span className="text-[10px] font-bold text-primary font-mono tracking-widest uppercase">
                    Scanner Active: {scanStatus.progress ? `${Math.round(scanStatus.progress * 100)}%` : 'Processing...'}
                  </span>
              </div>
            );
          })()}
        </div> 

        {/* Central Capsule Navigation */}
        <div className="hidden md:flex flex-1 justify-center">
            <div className="flex items-center bg-black/40 border border-white/10 rounded-full p-1 backdrop-blur-md shadow-[0_4px_20px_rgba(0,0,0,0.5)]">
                <button 
                  onClick={() => onNavigate('home')}
                  className={`px-6 py-1.5 rounded-full text-sm font-['Rajdhani'] font-bold transition-all duration-300 ${currentView === 'home' ? 'bg-primary/20 text-primary shadow-[inset_0_0_10px_rgba(var(--color-primary-rgb),0.3)]' : 'text-gray-400 hover:text-white'}`}
                >
                  首页
                </button>
                <div className="w-[1px] h-4 bg-white/10"></div>
                <button 
                  onClick={() => onNavigate('library')}
                  className={`px-6 py-1.5 rounded-full text-sm font-['Rajdhani'] font-bold transition-all duration-300 ${currentView === 'library' && activeLibraryId === null ? 'bg-primary/20 text-primary shadow-[inset_0_0_10px_rgba(var(--color-primary-rgb),0.3)]' : 'text-gray-400 hover:text-white'}`}
                >
                  全部
                </button>
                <div className="w-[1px] h-4 bg-white/10"></div>
                <button 
                  onClick={() => onNavigate('libraries')}
                  className={`px-6 py-1.5 rounded-full text-sm font-['Rajdhani'] font-bold transition-all duration-300 ${currentView === 'libraries' || (currentView === 'library' && activeLibraryId !== null) ? 'bg-primary/20 text-primary shadow-[inset_0_0_10px_rgba(var(--color-primary-rgb),0.3)]' : 'text-gray-400 hover:text-white'}`}
                >
                  片库
                </button>
            </div>
        </div>

        <div className="flex items-center gap-6 ml-auto flex-1 justify-end"> 
          <div className={`hidden md:flex items-center bg-black/40 border rounded-full px-3 py-1.5 transition-all duration-300 ease-in-out ${isSearchExpanded ? 'border-primary shadow-[0_0_10px_var(--color-primary)] bg-black/60' : 'border-white/10 hover:border-white/30 cursor-pointer'}`} onClick={() => { if (!isSearchExpanded) handleSearchClick(); }}> 
            <Search size={16} className={`transition-colors ${isSearchExpanded ? 'text-primary cursor-pointer' : 'text-gray-400'}`} onClick={(e) => { if (isSearchExpanded) { e.stopPropagation(); handleSearchClick(); } }} /> 
            <input 
              ref={searchInputRef}
              type="text" 
              placeholder="SEARCH ENTITY..." 
              value={searchValue} 
              onChange={(e) => setSearchValue(e.target.value)} 
              onKeyDown={handleKeyDown} 
              onBlur={() => { if(!searchValue) setIsSearchExpanded(false); }}
              className={`bg-transparent border-none outline-none text-white text-xs font-['Rajdhani'] transition-all duration-300 ease-in-out overflow-hidden placeholder-gray-600 ${isSearchExpanded ? 'w-48 ml-2 opacity-100' : 'w-0 ml-0 opacity-0'}`} 
            /> 
          </div> 
          <div className="flex items-center gap-4 text-gray-300 relative"> 
            <div className="cursor-pointer hover:text-primary transition-colors bg-white/5 p-2 rounded-full border border-white/5" onClick={() => onNavigate('history')} title="History"><Clock className={`w-4 h-4 ${currentView === 'history' ? 'text-primary' : ''}`} /></div> 
            <div className="relative cursor-pointer group bg-white/5 p-2 rounded-full border border-white/5" onClick={() => setShowNotifications(!showNotifications)}>
                <Bell className={`w-4 h-4 transition-colors ${showNotifications ? 'text-primary' : 'hover:text-accent'}`} />
                <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full animate-pulse shadow-[0_0_8px_#ff003c]"></span>
            </div> 
            
            {showNotifications && (
              <div className="absolute top-full right-0 mt-4 w-80 bg-[#0a0a12]/95 border border-primary/30 backdrop-blur-xl shadow-[0_0_30px_rgba(0,0,0,0.8)] z-50 flex flex-col max-h-[80vh] animate-in slide-in-from-top-2 fade-in duration-200 min-h-[300px]">
                <div className="p-4 border-b border-white/10 flex justify-between items-center bg-black/40">
                  <span className="text-sm font-['Orbitron'] font-bold text-primary tracking-wider flex items-center gap-2">{selectedNote ? (<button onClick={() => setSelectedNote(null)} className="flex items-center hover:text-white transition-colors"><ChevronLeft size={14} className="mr-1" /> BACK</button>) : (<><Sparkles size={14} /> SYSTEM_LOGS</>)}</span>
                  <button onClick={() => setShowNotifications(false)} className="text-gray-500 hover:text-white"><X size={16} /></button>
                </div>
                <div className="flex-1 overflow-y-auto">
                  {selectedNote ? (
                    <div className="p-6 animate-in slide-in-from-right-4 duration-200">
                      <div className="flex items-center gap-3 mb-4"><div className="p-2 rounded bg-black border border-white/20">{getNotificationIcon(selectedNote.type)}</div><div><div className="text-xs text-gray-500 font-['Rajdhani'] mb-1">{selectedNote.time}</div><div className="text-sm font-bold text-white font-['Orbitron'] text-primary">{selectedNote.title}</div></div></div>
                      <div className="w-full h-[1px] bg-white/10 mb-4"></div><p className="text-sm text-gray-300 leading-relaxed font-sans">{selectedNote.details || selectedNote.desc}</p>
                      <div className="mt-6 flex gap-2"><button className="flex-1 py-2 border border-primary/30 text-primary text-xs hover:bg-primary/10 transition-colors font-['Orbitron']">ARCHIVE</button><button className="flex-1 py-2 border border-white/10 text-gray-400 text-xs hover:bg-white/5 transition-colors font-['Orbitron']">DISMISS</button></div>
                    </div>
                  ) : (
                    <div className="py-2">{(notifications || []).map(note => (<div key={note.id} onClick={() => setSelectedNote(note)} className="px-4 py-3 hover:bg-white/5 border-l-2 border-transparent hover:border-primary transition-all group cursor-pointer"><div className="flex items-start gap-3"><div className="mt-1 p-1.5 rounded bg-black border border-white/10 group-hover:border-primary/50 transition-colors">{getNotificationIcon(note.type)}</div><div className="flex-1 min-w-0"><div className="flex justify-between items-center mb-1"><h4 className="text-xs font-bold text-white font-['Orbitron'] truncate pr-2 group-hover:text-primary transition-colors">{note.title}</h4><span className="text-[10px] text-gray-500 font-['Rajdhani'] whitespace-nowrap">{note.time}</span></div><p className="text-xs text-gray-400 leading-relaxed line-clamp-2 font-sans">{note.desc}</p></div></div></div>))}</div>
                  )}
                </div>
                {!selectedNote && (<div className="p-2 border-t border-white/10 bg-black/40 text-center"><button className="text-[10px] text-gray-500 hover:text-primary font-['Rajdhani'] tracking-widest w-full py-1 transition-colors">VIEW_ALL_LOGS_ARCHIVE</button></div>)}
              </div>
            )}
            {showNotifications && <div className="fixed inset-0 z-40" onClick={() => setShowNotifications(false)}></div>} 
            <div className="w-8 h-8 mx-1 bg-gradient-to-br from-primary to-secondary rounded-full border-2 border-white/20 overflow-hidden p-0.5 cursor-pointer hover:scale-110 shadow-[0_0_10px_rgba(var(--color-primary-rgb),0.5)] transition-transform flex items-center justify-center" onClick={onProfile}>
                <div className="w-full h-full bg-black rounded-full flex items-center justify-center">
                    <User size={16} className="text-white drop-shadow-[0_0_5px_rgba(255,255,255,0.8)]" />
                </div>
            </div> 
          </div> 
        </div> 
      </nav> 
    </>
  ); 
};

export const Footer = () => (
  <footer className="border-t border-white/10 bg-black py-12 relative z-10 mt-20"> 
    <div className="container mx-auto px-6 md:px-12"> 
      <div className="flex flex-col md:flex-row justify-between items-center gap-8"> 
        <div className="text-2xl font-['Orbitron'] font-bold text-gray-600">CYBER<span className="text-gray-800">STREAM</span></div> 
        <div className="flex gap-8 text-sm text-gray-500 font-['Rajdhani'] tracking-wider"><a href="#" className="hover:text-primary transition-colors">隐私协议</a><a href="#" className="hover:text-primary transition-colors">服务条款</a><a href="#" className="hover:text-primary transition-colors">帮助中心</a><a href="#" className="hover:text-primary transition-colors">企业联络</a></div> 
        <div className="text-xs text-gray-700 font-mono">© 2077 CYBERSTREAM CORP. ALL RIGHTS RESERVED.</div> 
      </div> 
    </div> 
  </footer>
);

export default Navbar;