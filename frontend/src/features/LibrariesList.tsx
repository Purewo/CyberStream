import React, { useEffect, useState } from 'react';
import { Library, Movie } from '../types';
import { FolderOpen } from 'lucide-react';
import { libraryService } from '../api';

interface LibrariesListProps {
  libraries: Library[];
  onSelectLibrary: (id: number) => void;
  onAddLibrary: () => void;
}

const LibraryCard = ({ lib, onClick }: { lib: Library, onClick: () => void }) => {
  const [posters, setPosters] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isActive = true;
    const fetchPosters = async () => {
      try {
        const res = await libraryService.getFilteredMovies(lib.id, 4);
        const movies = res.items || [];
        if (isActive) {
          const covers = movies.map(m => m.poster_url || m.cover_url || '').filter(Boolean);
          // Pad with empty strings if less than 4
          while (covers.length < 4) {
            covers.push('');
          }
          setPosters(covers.slice(0, 4));
        }
      } catch (e) {
        console.error(e);
      } finally {
        if (isActive) setIsLoading(false);
      }
    };
    fetchPosters();
    return () => { isActive = false; };
  }, [lib.id]);

  return (
    <div 
      onClick={onClick}
      className="flex flex-col group cursor-pointer relative"
    >
      <div className="relative flex flex-col bg-[#1a1a24] bg-gradient-to-b from-[#2a2a36] to-[#12121a] rounded-xl overflow-hidden border border-white/5 group-hover:border-white/20 shadow-[0_10px_20px_rgba(0,0,0,0.4)] group-hover:shadow-[0_20px_40px_rgba(0,0,0,0.6)] group-hover:-translate-y-2 transition-all duration-500">
        {/* Actual Posters */}
        <div className="flex h-48 w-full z-10 overflow-hidden bg-black/40 shadow-[0_10px_20px_rgba(0,0,0,0.8)] relative">
          {isLoading ? (
            <div className="w-full h-full flex items-center justify-center">
              <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin opacity-50"></div>
            </div>
          ) : (
            posters.map((url, i) => (
              <div key={i} className="flex-1 h-full relative bg-[#121216]">
                 {url ? (
                   <img src={url} className="w-full h-full object-cover" alt="" />
                 ) : (
                   <div className="w-full h-full flex flex-col items-center justify-center opacity-10">
                     <FolderOpen size={20} />
                   </div>
                 )}
                 <div className="absolute inset-0 bg-black/20 group-hover:bg-transparent transition-colors duration-500"></div>
              </div>
            ))
          )}
        </div>

        {/* Reflection Posters */}
        {!isLoading && (
          <div className="relative h-20 md:h-24 w-full overflow-hidden pointer-events-none -mt-[1px] z-0 [-webkit-mask-image:linear-gradient(to_bottom,white_0%,transparent_100%)] [mask-image:linear-gradient(to_bottom,white_0%,transparent_100%)]">
            <div className="flex w-full h-48 scale-y-[-1] opacity-50 blur-[2px]">
              {posters.map((url, i) => (
                <div key={i} className="flex-1 h-full bg-[#121216]">
                   {url && <img src={url} className="w-full h-full object-cover object-bottom" alt="" />}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="relative z-10 pt-5 pb-2 px-4 transition-transform duration-500 group-hover:-translate-y-2">
        <div className="text-center font-['Noto_Sans_SC'] font-bold text-gray-400 group-hover:text-white transition-colors tracking-widest text-[16px] drop-shadow-md">
          {lib.name}
        </div>
      </div>
    </div>
  );
};

export const LibrariesList: React.FC<LibrariesListProps> = ({ libraries, onSelectLibrary, onAddLibrary }) => {
  return (
    <div className="min-h-screen w-full pt-28 px-6 md:px-12 pb-12">
      <div className="flex items-center gap-4 mb-10"> 
        <div className="p-3 border border-primary text-primary shadow-[0_0_15px_var(--color-primary)] bg-primary/10 rounded-lg"> 
            <FolderOpen className="w-6 h-6" /> 
        </div> 
        <h1 className="text-3xl font-['Noto_Sans_SC'] font-bold text-white tracking-widest flex items-center gap-4"> 
           <span>我的 <span className="text-primary">资源库</span></span>
        </h1> 
        <div className="flex-grow h-[1px] bg-gradient-to-r from-primary/50 to-transparent"></div> 
      </div> 

      {libraries.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-6 mt-12 mb-12">
           <div className="h-64 w-full max-w-2xl flex flex-col items-center justify-center gap-4 text-gray-600 border border-white/5 bg-black/40 rounded-xl relative overflow-hidden group"> 
             <div className="absolute inset-0 bg-primary/5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></div>
             <FolderOpen size={48} className="opacity-20 group-hover:text-primary group-hover:opacity-50 transition-all transform group-hover:scale-110" /> 
             <div className="font-['Noto_Sans_SC'] tracking-widest text-xl group-hover:text-white transition-colors">暂无资源库</div> 
             <div className="text-sm font-sans text-gray-500">当前尚未配置媒体库，请与服务器同步或进行配置。</div> 
           </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-8">
          {libraries.map(lib => (
            <LibraryCard key={lib.id} lib={lib} onClick={() => onSelectLibrary(lib.id)} />
          ))}
        </div>
      )}
    </div>
  );
};
