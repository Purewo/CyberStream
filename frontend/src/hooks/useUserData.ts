import { useState, useEffect, useCallback } from 'react';
import { movieService, userService, systemService, libraryService, VaultError } from '../api';
import type { VaultAccessState } from '../api/user';
import { Movie, Notification, Library as LibraryType, HistoryItem } from '../types/index';
import { toast } from '../utils';

export function useUserData() {
  const [favorites, setFavorites] = useState<Movie[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [libraries, setLibraries] = useState<LibraryType[]>([]);
  // 保险库会话态：configured/unlocked/locked + 限额计数。整个 app 共享一份，
  // 详情页/右键菜单/Profile VAULT tab 都从这里读，避免各自重复请求。
  // null = 没权限（普通用户）或还没拉到。
  const [vaultState, setVaultState] = useState<VaultAccessState | null>(null);

  const refreshLibraries = useCallback(async () => {
    try {
      const libs = await libraryService.getLibraries();
      setLibraries(libs);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const refreshVaultStatus = useCallback(async () => {
    try {
      const v = await userService.getVaultStatus();
      setVaultState(v);
      return v;
    } catch {
      setVaultState(null);
      return null;
    }
  }, []);

  const refreshFavorites = useCallback(async () => {
    const fresh = await userService.getVault();
    setFavorites(fresh);
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const h = await userService.getHistory();
      setHistory(h);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const historyData = await userService.getHistory();
        setHistory(historyData);

        // vault status 先拉——保险库锁着的时候 getVault 会 403，没必要再拉一次空数组
        const vs = await refreshVaultStatus();
        if (vs?.unlocked) {
          await refreshFavorites();
        }

        const notificationsData = await systemService.getNotifications();
        setNotifications(notificationsData);

        const librariesData = await libraryService.getLibraries();
        setLibraries(librariesData);
      } catch (e) {
        console.error("Failed to fetch initial data", e);
      }
    };
    fetchData();
  }, [refreshFavorites, refreshVaultStatus]);

  const handleToggleFavorite = async (movie: Movie) => {
    const isFav = favorites.some(f => f.id === movie.id);
    // 乐观更新：先动 UI，失败再回滚。后端用 device_id 识别用户、幂等响应；
    // 保险库锁着或没 PIN 时会 403，UI 层提示去解锁。
    const optimistic = isFav
      ? favorites.filter(f => f.id !== movie.id)
      : [...favorites, movie];
    setFavorites(optimistic);
    try {
      const result = await userService.toggleFavorite(movie, isFav);
      const expected = !isFav;
      if (result.isFavorite !== expected) {
        // 后端 is_favorite 跟乐观结果不一致——以后端为准重拉
        await refreshFavorites();
      }
      const title = movie.title || '影片';
      toast.success(result.isFavorite ? `已收藏《${title}》` : `已取消收藏《${title}》`);
    } catch (e) {
      console.error('toggleFavorite failed', e);
      setFavorites(favorites); // 回滚
      if (e instanceof VaultError) {
        if (e.http === 403) {
          toast.error('请先在「数据保险库」中解锁');
        } else if (e.http === 423) {
          toast.error('保险库已被锁定，请稍后再试');
        } else {
          toast.error(e.message || '保险库不可用');
        }
      } else {
        toast.error(isFav ? '取消收藏失败' : '加入收藏失败');
      }
    }
  };

  const handleClearHistory = async () => {
    // 乐观清空。后端真删失败时回滚并提示，避免"看着删了实际还在"。
    const previous = history;
    setHistory([]);
    const res = await userService.clearHistory();
    if (!res.ok) {
      setHistory(previous);
      toast.error(`清空历史失败：${res.msg || '请重试'}`);
      return;
    }
    // 幽灵成就：清除观看历史。
    const { unlockBehaviorAchievement } = await import('../api');
    unlockBehaviorAchievement('ghost');
  };

  const handleDeleteHistoryItem = async (resourceId: string) => {
    if (!resourceId) return;
    const previous = history;
    setHistory(prev => prev.filter(item => item.resourceId !== resourceId));
    const res = await userService.deleteHistoryItem(resourceId);
    if (!res.ok) {
      setHistory(previous);
      toast.error(`删除记录失败：${res.msg || '请重试'}`);
    }
  };

  return {
    favorites, handleToggleFavorite, refreshFavorites, setFavorites,
    history, setHistory, handleClearHistory, handleDeleteHistoryItem, refreshHistory,
    notifications,
    libraries, setLibraries, refreshLibraries,
    vaultState, refreshVaultStatus, setVaultState,
  };
}
