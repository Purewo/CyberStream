import React, { useEffect } from 'react';
import Navbar, { Footer } from './components/layout/Navbar';
import { Home, Library, Leaderboard, HistoryPage, SearchResults, ReviewWorkbench } from './features/Views';
import { ProfilePage } from './features/Profile';
import { MovieDetail } from './features/MovieDetail';
import { MetadataEditor } from './features/MetadataEditor';
import { Player } from './components/Player';
import { LibrariesList } from './features/LibrariesList';
import { AddLibraryWizard } from './features/AddLibraryWizard';
import { AddToLibraryModal } from './features/AddToLibraryModal';
import { ContextMenu } from './components/ui/ContextMenu';
import { ScanProgressBar } from './components/ui/ScanProgressBar';
import { Toaster } from './components/ui/Toaster';
import { movieService, libraryService, userService } from './api';
import { getStyles, toast } from './utils';
import { Movie } from './types';
import { useThemeSettings } from './hooks/useThemeSettings';
import { useUserData } from './hooks/useUserData';
import { useAppRouting } from './hooks/useAppRouting';

const App = () => { 
  const { settings, setSettings, themeName, setThemeName, currentTheme } = useThemeSettings();
  const { 
    favorites, handleToggleFavorite, 
    history, setHistory, handleClearHistory, handleDeleteHistoryItem, refreshHistory,
    notifications, 
    libraries, setLibraries, refreshLibraries 
  } = useUserData();

  const {
    currentView, setCurrentView,
    profileInitialTab, setProfileInitialTab,
    overlayView, setOverlayView,
    scrollContainerRef, savedScroll, setSavedScroll,
    libraryInitialType, setLibraryInitialType,
    selectedMovie, setSelectedMovie,
    activeLibraryId, setActiveLibraryId,
    searchQuery, setSearchQuery,
    searchResults, setSearchResults,
    playOptions, setPlayOptions,
    contextMenu, setContextMenu,
    metadataMovie, setMetadataMovie,
    addToLibraryMovie, setAddToLibraryMovie,
    navigateTo, closeOverlay, openMovie: handleMovieSelect, openPlayer
  } = useAppRouting();
  


  // Global Context Menu Event Listener
  useEffect(() => {
    const handleContextMenuEvent = (e: CustomEvent) => {
      setContextMenu({ visible: true, x: e.detail.x, y: e.detail.y, movie: e.detail.movie });
    };
    window.addEventListener('show-movie-context-menu', handleContextMenuEvent as EventListener);
    return () => window.removeEventListener('show-movie-context-menu', handleContextMenuEvent as EventListener);
  }, []);
  

  const handleSearch = async (query: string) => { 
    setSearchQuery(query); 
    navigateTo('search'); 
    try { 
      const data = await movieService.search(query); 
      setSearchResults(data); 
    } catch (e) { 
      console.error("Search failed", e); 
    } 
  }; 
  

  
  const handleNavigate = (view: ViewState) => { 
    if (view === 'history') { 
      refreshHistory();
    } 
    navigateTo(view); 
  }; 
  
  const handleViewCategory = (categoryId: string) => { 
    const mapping: Record<string, string> = { 'scifi': '科幻', 'action': '动作', 'romance': '剧情', 'anime': '动画' }; 
    const filterLabel = mapping[categoryId] || "全部类型"; 
    navigateTo('library', { libraryInitialType: filterLabel }); 
  }; 
  
  const handleContextMenuAction = async (action: string, movie: Movie) => {
    setContextMenu(prev => ({ ...prev, visible: false }));
    switch (action) {
       case 'add_to_library':
         if (libraries.length === 0) {
           alert("当前没有任何片库，请先创建片库！");
           navigateTo('libraries');
         } else {
           setAddToLibraryMovie(movie);
         }
         break;
       case 'remove_from_library':
         if (activeLibraryId) {
           // We attempt to delete any manual include/exclude rule first
           await libraryService.deleteMovieMemberships(activeLibraryId, [String(movie.id)]);
           // Then we explicitly exclude it to override directory matches
           const success = await libraryService.createMovieMembership(activeLibraryId, 'exclude', [String(movie.id)]);
           if (success) {
             toast.success(`《${movie.title}》已从当前片库移除。`);
             window.dispatchEvent(new CustomEvent('library-list-dirty'));
           } else {
             toast.error("移除失败，请重试。");
           }
         }
         break;
       case 'scrape':
         // Try to do a real scrape
         const doScrape = async () => {
             alert(`正在联系数据源中心，重新抓取《${movie.title}》的神经元数据...`);
             try {
                const refreshed = await movieService.reScrapeMetadata(String(movie.id), { force_refresh: true });
                if (refreshed) {
                  if (selectedMovie && selectedMovie.id === movie.id) {
                     setSelectedMovie(refreshed);
                  }
                  alert(`《${movie.title}》元数据重刮完成！`);
                } else {
                  alert(`《${movie.title}》元数据重刮失败，后端未返回有效实体。`);
                }
             } catch (e) {
                console.error(e);
             }
         };
         doScrape();
         break;
       case 'edit':
         setMetadataMovie(movie);
         break;
       case 'share':
         navigator.clipboard.writeText(`你看《${movie.title}》了吗？超赞：${window.location.origin}/movie/${movie.id}`);
         alert('分享链接已复制到剪贴板！'); 
         break;
       case 'favorite':
         await handleToggleFavorite(movie);
         break;
       case 'watched':
         // Simulate marking as watched locally + report to API if possible
         await userService.reportHistory(String(movie.id), movie.duration || 3600, movie.duration || 3600);
         setHistory(prev => [{ ...movie, resourceId: String(movie.id), progress: 1, duration: 1, updated_at: new Date().toISOString() }, ...prev]);
         break;
       case 'delete':
         // Removed window.confirm because it is blocked in iframe environment
         const success = await movieService.delete(movie.id);
         if (success) {
           if (selectedMovie && selectedMovie.id === movie.id) {
               closeOverlay();
               setSelectedMovie(null);
           }
           toast.success(`档案《${movie.title}》已销毁。`);
           window.dispatchEvent(new CustomEvent('library-list-dirty'));
         } else {
           toast.error("档案销毁任务失败，请检查数据库权限。");
         }
         break;
    }
  };

  return (
    <div className="min-h-screen font-sans selection:bg-secondary selection:text-white relative bg-[#050505] text-white flex overflow-hidden" style={{ backgroundColor: currentTheme.bg }}> 
      <style>{getStyles(settings, currentTheme)}</style> 
      <div className="scanlines pointer-events-none z-[100]"></div> 
      <div className="perspective-grid"></div> 

      <div ref={scrollContainerRef} className={`flex-1 flex flex-col relative w-full h-screen overflow-y-auto transition-all duration-300`}>
        {overlayView !== 'player' && (
          <Navbar onNavigate={handleNavigate} currentView={currentView} activeLibraryId={activeLibraryId} onSearch={handleSearch} onProfile={() => { setProfileInitialTab('IDENTITY'); setCurrentView('profile'); setOverlayView('none'); setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0; }, 0); }} notifications={notifications} hideLogo={overlayView === 'detail'} />
        )}

        <main className={`flex-1 flex flex-col w-full`}>
          <div style={{ display: overlayView === 'none' ? 'block' : 'none', flex: 1, minHeight: 0 }}>
            {currentView === 'home' && (<Home onMovieSelect={handleMovieSelect} onViewMore={handleViewCategory} />)} 
            {currentView === 'library' && (<Library onMovieSelect={handleMovieSelect} initialType={libraryInitialType} activeLibraryId={activeLibraryId} onRequestBind={() => { setProfileInitialTab('LIBRARIES'); setCurrentView('profile'); setOverlayView('none'); }} />)} 
            {currentView === 'libraries' && (<LibrariesList libraries={libraries} onSelectLibrary={(id) => { setActiveLibraryId(id); setCurrentView('library'); }} onAddLibrary={() => setCurrentView('add_library')} />)}
            {currentView === 'add_library' && (<AddLibraryWizard onCancel={() => setCurrentView('libraries')} onSuccess={() => {
              refreshLibraries();
              setCurrentView('libraries');
            }} />)}
            {currentView === 'leaderboard' && (<Leaderboard onMovieSelect={handleMovieSelect} />)} 
            {currentView === 'history' && (<HistoryPage history={history} onMovieSelect={handleMovieSelect} onClearHistory={handleClearHistory} onDeleteHistoryItem={handleDeleteHistoryItem} />)} 
            {currentView === 'profile' && (<ProfilePage initialTab={profileInitialTab} settings={settings} setSettings={setSettings} favorites={favorites} onToggleFavorite={handleToggleFavorite} onMovieSelect={handleMovieSelect} currentTheme={themeName} setTheme={setThemeName} libraries={libraries} history={history} onClearHistory={handleClearHistory} onDeleteHistoryItem={handleDeleteHistoryItem} onRefreshLibraries={refreshLibraries} />)} 
            {currentView === 'search' && (<SearchResults query={searchQuery} results={searchResults} onMovieSelect={handleMovieSelect} />)} 
            {currentView === 'review' && (<ReviewWorkbench />)}
          </div>
          
          {overlayView === 'detail' && selectedMovie && (
            <MovieDetail movie={selectedMovie} history={history} onBack={() => {
              setOverlayView('none');
              setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = savedScroll; }, 0);
            }} 
              onPlay={(options = {}) => { setPlayOptions(options); setOverlayView('player'); }} 
              onMovieSelect={handleMovieSelect} 
              isFavorite={favorites.some(f => f.id === selectedMovie.id)} 
              onToggleFavorite={handleToggleFavorite} 
              onUpdateMovie={(updatedMovie) => {
                setSelectedMovie(updatedMovie);
              }}
            />
          )} 
          
          {overlayView === 'player' && selectedMovie && (
            <Player movie={selectedMovie} initialOptions={playOptions} onBack={() => {
                setOverlayView('detail');
                refreshHistory();
            }} />
          )} 
          
          {overlayView !== 'player' && <Footer />} 
        </main>
      </div>

      {/* Global Context Menu */}
      <ContextMenu 
        visible={contextMenu.visible} 
        x={contextMenu.x} 
        y={contextMenu.y} 
        movie={contextMenu.movie} 
        activeLibraryId={currentView === 'library' ? activeLibraryId : null}
        isFavorite={contextMenu.movie ? favorites.some(f => f.id === contextMenu.movie!.id) : false}
        onClose={() => setContextMenu(prev => ({ ...prev, visible: false }))}
        onAction={handleContextMenuAction}
      />

      {/* Add to Library Modal */}
      {addToLibraryMovie && (
        <AddToLibraryModal
          movie={addToLibraryMovie}
          libraries={libraries}
          onClose={() => setAddToLibraryMovie(null)}
          onAdded={() => {
            // Optional: trigger library refresh if we want, but it's okay not to
          }}
        />
      )}

      {/* Global Metadata Editor */}
      {metadataMovie && (
        <MetadataEditor 
          movie={metadataMovie}
          onClose={() => setMetadataMovie(null)}
          onUpdateQuietly={(updatedMovie) => {
            if (selectedMovie && selectedMovie.id === updatedMovie.id) {
              setSelectedMovie(updatedMovie);
            }
          }}
          onSave={(updatedMovie) => {
            setMetadataMovie(null);
            // Also update selectedMovie if it's the one being edited
            if (selectedMovie && selectedMovie.id === updatedMovie.id) {
              setSelectedMovie(updatedMovie);
            }
          }}
        />
      )}

      {/* Global Scan Progress */}
      <ScanProgressBar />

      {/* Global Notification System */}
      <Toaster />
    </div>
  ); 
}; 

export default App;