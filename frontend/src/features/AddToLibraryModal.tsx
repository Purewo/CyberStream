import React, { useState } from 'react';
import { LibraryType, Movie } from '../types';
import { libraryService } from '../api';
import { X, FolderPlus } from 'lucide-react';

interface AddToLibraryModalProps {
  movie: Movie;
  libraries: LibraryType[];
  onClose: () => void;
  onAdded: () => void;
}

export const AddToLibraryModal: React.FC<AddToLibraryModalProps> = ({ movie, libraries, onClose, onAdded }) => {
  const [addingTo, setAddingTo] = useState<number[]>([]);

  const handleAddToLibrary = async (libraryId: number) => {
    try {
      setAddingTo(prev => [...prev, libraryId]);
      const success = await libraryService.createMovieMembership(libraryId, 'include', [String(movie.id)]);
      if (success) {
        alert(`已成功将《${movie.title}》添加到片库`);
        onAdded();
        onClose();
      } else {
        alert('添加失败，请重试');
      }
    } catch (e) {
      console.error(e);
      alert('添加时出现错误');
    } finally {
      setAddingTo(prev => prev.filter(id => id !== libraryId));
    }
  };

  return (
    <div className="fixed inset-0 z-[200] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#12121A] border border-white/10 rounded-xl max-w-md w-full p-6 relative animate-in fade-in zoom-in-95">
        <button onClick={onClose} className="absolute right-4 top-4 text-gray-400 hover:text-white transition-colors">
          <X size={20} />
        </button>
        
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center text-primary">
            <FolderPlus size={20} />
          </div>
          <div>
            <h3 className="text-xl font-['Orbitron'] font-bold text-white">添加到片库</h3>
            <p className="text-xs text-gray-400 font-sans mt-1">选择要把《{movie.title}》加入到的片库</p>
          </div>
        </div>
        
        <div className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-2 custom-scrollbar">
          {libraries.length === 0 ? (
            <p className="text-gray-500 text-sm py-4 text-center">暂无可用片库</p>
          ) : (
            libraries.map(lib => (
              <button
                key={lib.id}
                disabled={addingTo.includes(lib.id)}
                onClick={() => handleAddToLibrary(lib.id)}
                className="flex items-center justify-between p-3 rounded-lg border border-white/5 bg-white/5 hover:bg-white/10 hover:border-primary/50 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed group"
              >
                <div className="flex flex-col">
                  <span className="font-['Noto_Sans_SC'] font-bold text-gray-200 group-hover:text-primary transition-colors">{lib.name}</span>
                  {lib.description && <span className="text-xs text-gray-500 line-clamp-1">{lib.description}</span>}
                </div>
                <span className="text-primary text-xs opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap ml-4">
                  {addingTo.includes(lib.id) ? '添加中...' : '点击添加 ->'}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
