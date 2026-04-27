import { useState, useRef } from 'react';
import { ViewState, Movie, PlayOptions } from '../types/index';

export function useAppRouting() {
  const [currentView, setCurrentView] = useState<ViewState>('home'); 
  const [profileInitialTab, setProfileInitialTab] = useState<string>('IDENTITY');
  const [overlayView, setOverlayView] = useState<'none' | 'detail' | 'player'>('none');
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [savedScroll, setSavedScroll] = useState(0);
  const [libraryInitialType, setLibraryInitialType] = useState("全部类型"); 
  const [selectedMovie, setSelectedMovie] = useState<Movie | null>(null); 
  const [activeLibraryId, setActiveLibraryId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState(''); 
  const [searchResults, setSearchResults] = useState<Movie[]>([]); 
  const [playOptions, setPlayOptions] = useState<PlayOptions>({}); 

  // Modal States
  const [contextMenu, setContextMenu] = useState<{ visible: boolean, x: number, y: number, movie: Movie | null }>({ visible: false, x: 0, y: 0, movie: null });
  const [metadataMovie, setMetadataMovie] = useState<Movie | null>(null);
  const [addToLibraryMovie, setAddToLibraryMovie] = useState<Movie | null>(null);

  const navigateTo = (view: ViewState, options?: { libraryId?: number | null, libraryInitialType?: string }) => {
    if (view === 'library') { 
      setActiveLibraryId(options?.libraryId || null);
      setLibraryInitialType(options?.libraryInitialType || "全部类型"); 
    }
    setCurrentView(view);
    setOverlayView('none');
    setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0; }, 0);
  };

  const closeOverlay = () => {
    setOverlayView('none');
    setTimeout(() => { if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = savedScroll; }, 0);
  };

  const openMovie = (movie: Movie) => {
    if (scrollContainerRef.current && overlayView === 'none') {
      setSavedScroll(scrollContainerRef.current.scrollTop);
    }
    
    let mergedMovie = { ...movie };
    if (mergedMovie.target_season !== undefined && mergedMovie.season_cards) {
        const sc = mergedMovie.season_cards.find(c => c.season === mergedMovie.target_season);
        if (sc) {
            if (sc.poster_url && sc.has_distinct_poster) {
                mergedMovie.poster_url = sc.poster_url;
                mergedMovie.cover_url = sc.poster_url;
            }
            if (sc.overview) {
                mergedMovie.overview = sc.overview;
                mergedMovie.desc = sc.overview;
            }
        }
    }

    setSelectedMovie(mergedMovie);
    setOverlayView('detail');
  };

  const openPlayer = (options: PlayOptions = {}) => {
    setPlayOptions(options); 
    setOverlayView('player');
  };

  return {
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
    navigateTo, closeOverlay, openMovie, openPlayer
  };
}
