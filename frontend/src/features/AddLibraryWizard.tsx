import React, { useState, useEffect } from 'react';
import { Film, Tv, PlaySquare, ListVideo, FolderOpen, Save, ChevronRight, ChevronLeft, HardDrive, Check, Loader2 } from 'lucide-react';
import { libraryService, storageService } from '../api';
import { StorageSource } from '../types';

interface AddLibraryWizardProps {
  onCancel: () => void;
  onSuccess: () => void;
}

export const AddLibraryWizard: React.FC<AddLibraryWizardProps> = ({ onCancel, onSuccess }) => {
  const [step, setStep] = useState<1 | 2>(1);
  
  // Library Basic Info
  const [libraryName, setLibraryName] = useState('');
  
  // Sources Binding
  const [storageSources, setStorageSources] = useState<StorageSource[]>([]);
  const [selectedSources, setSelectedSources] = useState<number[]>([]);
  
  const [isSaving, setIsSaving] = useState(false);
  const [errorInfo, setErrorInfo] = useState<string | null>(null);

  useEffect(() => {
    storageService.getSources().then(setStorageSources).catch(console.error);
  }, []);

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'movie': return <Film size={32} />;
      case 'tv': return <Tv size={32} />;
      case 'anime': return <PlaySquare size={32} />;
      default: return <ListVideo size={32} />;
    }
  };

  const getTypes = () => [
    { id: 'movie', label: 'Movies', icon: <Film size={24} />, desc: 'Feature films and movies.' },
    { id: 'tv', label: 'TV Shows', icon: <Tv size={24} />, desc: 'Episodic television shows.' },
    { id: 'anime', label: 'Anime', icon: <PlaySquare size={24} />, desc: 'Japanese animation.' },
    { id: 'mixed', label: 'Mixed', icon: <ListVideo size={24} />, desc: 'A mix of various content types.' }
  ];

  const handleNext = () => {
    if (step === 1 && !libraryName.trim()) {
      setErrorInfo('Please enter a library name.');
      return;
    }
    setErrorInfo(null);
    setStep(2);
  };

  const handleCreate = async () => {
    setIsSaving(true);
    setErrorInfo(null);
    try {
      const slug = libraryName.toLowerCase().replace(/\s+/g, '-');
      const libraryId = await libraryService.createLibrary(libraryName, slug);
      
      if (libraryId === null) {
        throw new Error("Failed to create library in the backend.");
      }

      // Bind selected sources
      for (const sourceId of selectedSources) {
        await libraryService.bindLibrarySource(libraryId, sourceId, '/');
      }

      onSuccess();
    } catch (e: any) {
      console.error(e);
      setErrorInfo(e.message || "An error occurred while creating the library.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="min-h-screen w-full pt-28 px-6 md:px-12 pb-12 flex flex-col items-center">
      <div className="w-full max-w-4xl">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-primary/10 border border-primary text-primary rounded-lg shadow-[0_0_15px_var(--color-primary)]">
              <FolderOpen className="w-6 h-6" />
            </div>
            <h1 className="text-3xl font-['Orbitron'] font-bold text-white tracking-widest uppercase">
              Add <span className="text-primary">Library</span>
            </h1>
          </div>
          <div className="flex items-center gap-2 font-['Orbitron'] text-xs font-bold text-gray-500">
            <span className={step === 1 ? "text-primary drop-shadow-[0_0_5px_var(--color-primary)]" : "text-white"}>01 TYPE & NAME</span>
            <ChevronRight size={14} className="mx-2 opacity-50" />
            <span className={step === 2 ? "text-primary drop-shadow-[0_0_5px_var(--color-primary)]" : "text-gray-500"}>02 ADD SOURCES</span>
          </div>
        </div>

        {errorInfo && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg text-sm font-bold flex items-center justify-center">
            {errorInfo}
          </div>
        )}

        <div className="bg-[#0a0a12]/80 border border-white/10 rounded-2xl p-8 relative overflow-hidden backdrop-blur-md min-h-[400px] flex flex-col">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent pointer-events-none"></div>

          {step === 1 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-300 flex-1 flex flex-col relative z-10">
              <h2 className="text-xl font-bold font-['Orbitron'] mb-6 text-white border-b border-white/10 pb-4">NAME YOUR LIBRARY</h2>
              <div className="flex-1">
                <input 
                  type="text" 
                  value={libraryName} 
                  onChange={(e) => setLibraryName(e.target.value)} 
                  placeholder="e.g. Action Movies" 
                  autoFocus
                  className="w-full bg-black/60 border border-white/20 focus:border-primary focus:bg-black/80 rounded-xl px-6 py-4 text-xl text-white outline-none transition-all shadow-[inset_0_0_10px_rgba(0,0,0,0.5)] focus:shadow-[0_0_20px_rgba(var(--color-primary-rgb),0.1)] font-['Rajdhani']"
                />
              </div>

              <div className="pt-6 mt-auto border-t border-white/10 flex justify-between items-center">
                 <button onClick={onCancel} className="px-6 py-3 rounded-xl border border-white/10 hover:bg-white/5 transition-colors font-['Orbitron'] text-gray-400 font-bold text-sm">CANCEL</button>
                 <button onClick={handleNext} className="px-8 py-3 rounded-xl bg-primary text-black hover:bg-white transition-colors font-['Orbitron'] font-bold text-sm flex items-center gap-2 shadow-[0_0_20px_var(--color-primary)]">NEXT <ChevronRight size={18} /></button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-300 flex-1 flex flex-col relative z-10">
              <h2 className="text-xl font-bold font-['Orbitron'] mb-2 text-white flex items-center gap-3">
                <span className="text-primary"><FolderOpen size={32} /></span> 
                ADD FOLDERS TO "{String(libraryName).toUpperCase()}"
              </h2>
              <p className="text-sm text-gray-400 mb-6 border-b border-white/10 pb-6">
                Select the storage sources you want to include in this library. You can manage path bindings globally later.
              </p>
              
              <div className="flex-1 overflow-y-auto mb-6 custom-scrollbar pr-2">
                 {storageSources.length === 0 ? (
                    <div className="bg-black/40 border border-white/5 rounded-xl p-8 flex flex-col items-center justify-center text-gray-500 gap-4">
                      <HardDrive size={48} className="opacity-20" />
                      <p className="font-mono text-sm">No storage sources configured.</p>
                      <p className="font-sans text-xs max-w-sm text-center">You can create this library without sources and add them later from the profile settings. Or go to your profile to configure storage nodes first.</p>
                    </div>
                 ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {storageSources.map(source => (
                         <div 
                           key={source.id} 
                           onClick={() => setSelectedSources(prev => prev.includes(source.id) ? prev.filter(x => x !== source.id) : [...prev, source.id])}
                           className={`p-4 rounded-xl border cursor-pointer flex flex-col transition-all group ${selectedSources.includes(source.id) ? 'bg-primary/10 border-primary shadow-[inset_0_0_15px_rgba(var(--color-primary-rgb),0.2)]' : 'bg-black/50 border-white/10 hover:border-white/30'}`}
                         >
                           <div className="flex justify-between items-start mb-2">
                             <div className="p-2 rounded bg-white/5 group-hover:bg-primary/10 transition-colors">
                                <HardDrive size={18} className={selectedSources.includes(source.id) ? 'text-primary' : 'text-gray-400'} />
                             </div>
                             <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${selectedSources.includes(source.id) ? 'bg-primary border-primary text-black' : 'border-white/20'}`}>
                                {selectedSources.includes(source.id) && <Check size={14} />}
                             </div>
                           </div>
                           <h3 className="font-bold text-white truncate group-hover:text-primary transition-colors">{source.name}</h3>
                           <p className="text-xs text-gray-500 font-mono mt-1 opacity-80" title={source.type || 'UNKNOWN'}>{(source.type || 'UNKNOWN').toUpperCase()}</p>
                         </div>
                      ))}
                    </div>
                 )}
              </div>

              <div className="pt-6 mt-auto border-t border-white/10 flex justify-between items-center">
                 <button onClick={() => setStep(1)} className="px-6 py-3 rounded-xl border border-white/10 hover:bg-white/5 transition-colors font-['Orbitron'] text-gray-400 font-bold text-sm flex items-center gap-2"><ChevronLeft size={18} /> BACK</button>
                 <button onClick={handleCreate} disabled={isSaving} className="px-8 py-3 rounded-xl bg-primary text-black hover:bg-white transition-colors font-['Orbitron'] font-bold text-sm flex items-center gap-2 shadow-[0_0_20px_var(--color-primary)] disabled:opacity-50 disabled:cursor-not-allowed">
                   {isSaving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />} 
                   CREATE
                 </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
