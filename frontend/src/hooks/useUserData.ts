import { useState, useEffect } from 'react';
import { movieService, userService, systemService, libraryService } from '../api';
import { Movie, Notification, Library as LibraryType } from '../types/index';

export function useUserData() {
  const [favorites, setFavorites] = useState<Movie[]>([]); 
  const [history, setHistory] = useState<any[]>([]); 
  const [notifications, setNotifications] = useState<Notification[]>([]); 
  const [libraries, setLibraries] = useState<LibraryType[]>([]);

  useEffect(() => { 
    const fetchData = async () => { 
      try {
        const historyData = await userService.getHistory();
        setHistory(historyData);
        
        const vaultData = await userService.getVault();
        setFavorites(vaultData);
        
        const notificationsData = await systemService.getNotifications();
        setNotifications(notificationsData);

        const librariesData = await libraryService.getLibraries();
        setLibraries(librariesData);
      } catch (e) {
        console.error("Failed to fetch initial data", e);
      }
    }; 
    fetchData(); 
  }, []); 

  const handleToggleFavorite = async (movie: Movie) => { 
    const isFav = favorites.some(f => f.id === movie.id); 
    let newFavs; 
    if (isFav) { 
      newFavs = favorites.filter(f => f.id !== movie.id); 
    } else { 
      newFavs = [...favorites, movie]; 
    } 
    setFavorites(newFavs); 
    await userService.toggleFavorite(movie); 
  }; 

  const handleClearHistory = async () => { 
    await userService.clearHistory();
    setHistory([]); 
  }; 

  const handleDeleteHistoryItem = async (resourceId: string) => {
    await userService.deleteHistoryItem(resourceId);
    setHistory(prev => prev.filter(item => item.resourceId !== resourceId));
  };

  const refreshLibraries = async () => {
    try {
        const libs = await libraryService.getLibraries();
        setLibraries(libs);
    } catch (e) {
        console.error(e);
    }
  };

  const refreshHistory = async () => {
    try {
        const h = await userService.getHistory();
        setHistory(h);
    } catch (e) {
        console.error(e);
    }
  };

  return {
    favorites, handleToggleFavorite,
    history, setHistory, handleClearHistory, handleDeleteHistoryItem, refreshHistory,
    notifications,
    libraries, setLibraries, refreshLibraries
  };
}
