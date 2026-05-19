import React, { useEffect, useRef } from 'react';
// ContextMenu UI Component
import { Movie } from '../../types';
import { Edit3, Share2, Heart, CheckCircle2, Trash2, X, RefreshCw, FolderPlus, FolderMinus } from 'lucide-react';

interface ContextMenuProps {
  visible: boolean;
  x: number;
  y: number;
  movie: Movie | null;
  isFavorite: boolean;
  activeLibraryId?: number | null;
  onClose: () => void;
  onAction: (action: string, movie: Movie) => void;
}

export const ContextMenu: React.FC<ContextMenuProps> = ({ visible, x, y, movie, isFavorite, activeLibraryId, onClose, onAction }) => {
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on click outside or escape
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    const handleScroll = () => {
       onClose();
    };

    if (visible) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEsc);
      window.addEventListener('scroll', handleScroll, { passive: true });
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEsc);
      window.removeEventListener('scroll', handleScroll);
    };
  }, [visible, onClose]);

  if (!visible || !movie) return null;

  // Ensure menu stays within viewport bounds
  const px = Math.min(x, window.innerWidth - 220); // 220 is approx max width
  let py = y;
  // If we know height approx 240, adjust if it goes off bottom
  if (py + 240 > window.innerHeight) {
     py = window.innerHeight - 240;
  }

    const menuItems = [
    { id: 'scrape', icon: <RefreshCw size={15} />, label: '全网检索匹配', color: 'hover:text-purple-400' },
    { id: 'edit', icon: <Edit3 size={15} />, label: '编辑元数据', color: 'hover:text-amber-400' },
    { id: 'add_to_library', icon: <FolderPlus size={15} />, label: '添加到片库...', color: 'hover:text-teal-400' },
    ...(activeLibraryId ? [{ id: 'remove_from_library', icon: <FolderMinus size={15} />, label: '从当前片库移除', color: 'hover:text-red-400' }] : []),
    { id: 'share', icon: <Share2 size={15} />, label: '协议分享', color: 'hover:text-blue-400' },
    { id: 'favorite', icon: <Heart size={15} className={isFavorite ? 'fill-red-500 text-red-500' : ''} />, label: isFavorite ? '取消保险库' : '存入保险库', color: isFavorite ? 'hover:text-red-400' : 'hover:text-pink-400' },
    { id: 'watched', icon: <CheckCircle2 size={15} />, label: '标记已看', color: 'hover:text-green-400' },
    { id: 'delete', icon: <Trash2 size={15} />, label: '覆写销毁', color: 'hover:text-red-500 hover:bg-red-500/10' },
  ];

  return (
    <div 
      ref={menuRef}
      className="fixed z-[100] w-52 bg-[#12121A]/80 backdrop-blur-2xl border border-white/10 rounded-xl shadow-[0_8px_30px_rgb(0,0,0,0.7)] flex flex-col p-1 animate-in fade-in zoom-in-95 duration-150 transform-gpu"
      style={{ left: px, top: py, transformOrigin: 'top left' }}
    >
      <div className="px-3 pt-2 pb-3 mb-1 border-b border-white/5 mx-1">
        <h4 className="text-white font-bold text-sm truncate">{movie.title}</h4>
        <p className="text-[10px] tracking-wider text-gray-500 font-['Orbitron'] mt-0.5">SYS_ID: {String(movie.id).substring(0,8).toUpperCase()}</p>
      </div>

      <div className="flex flex-col gap-0.5">
        {menuItems.map((item) => (
          <button
            key={item.id}
            onClick={(e) => {
               e.stopPropagation();
               onAction(item.id, movie);
            }}
            className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm text-gray-300 transition-all rounded-lg bg-transparent hover:bg-white/10 ${item.color} active:scale-[0.98] active:bg-white/5 group`}
          >
            <div className="text-gray-400 group-hover:text-inherit transition-colors">{item.icon}</div>
            <span className="font-medium tracking-wide">{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
