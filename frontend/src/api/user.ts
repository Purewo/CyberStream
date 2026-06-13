import { getApiBase } from '../platform';
import { fetchApi, fetchApiRaw, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries, Achievement, AchievementSummary } from '../types/index';

/** 保险库 / 收藏访问态。后端 vault/status / unlock / lock / password 都返回这个结构。 */
export interface VaultAccessState {
  configured: boolean;
  unlocked: boolean;
  locked: boolean;
  locked_until?: string | null;
  pin_change_limit_per_day: number;
  pin_changes_used_today: number;
  pin_changes_remaining_today: number;
}

/** 抛给 UI 层用的 vault 错误。code 是后端业务码（40340 等）；http 是 HTTP 状态码。 */
export class VaultError extends Error {
  code?: number;
  http: number;
  constructor(code: number | undefined, msg: string | undefined, http: number) {
    super(msg || `Vault error (HTTP ${http})`);
    this.code = code;
    this.http = http;
    this.name = 'VaultError';
  }
}

export const userService = {
  getHistory: async (): Promise<HistoryItem[]> => {
    try {
      // 后端默认 page_size=20、上限 100。普通用户历史不会超过几十条，
      // 一次拉满 100 比做客户端翻页 UI 简单很多；上限内能完整覆盖大多数
      // 用户。真有重度用户超过 100 条时才考虑加载更多按钮。
      const data = await fetchApi<any>('/v1/user/history?page_size=100');
      if (!data) return [];

      let items: any[] = [];
      // API might return array directly OR { items: [...] } OR { data: [...] }
      if (Array.isArray(data)) {
          items = data;
      } else if (typeof data === 'object') {
          if (Array.isArray(data.items)) items = data.items;
          else if (Array.isArray(data.data)) items = data.data;
          else if (data.data && Array.isArray(data.data.items)) items = data.data.items;
      }

      return items.map(item => {
        const movieInfo = item.movie || item; 
        const movie = mapApiMovieToUi(movieInfo);
        
        const updatedAt = item.updated_at || item.created_at || new Date().toISOString();
        let dateObj = new Date(updatedAt);
        if (isNaN(dateObj.getTime())) dateObj = new Date();
        
        // Spec 1.16.0-beta uses position_sec and total_duration
        const progress = Number(item.position_sec || item.progress || 0);
        const duration = Number(item.total_duration || item.duration || movie.duration || 0);

        // Find matched season_card for history item
        const targetSeason = item.season || movie.target_season;
        if (targetSeason !== undefined && movie.season_cards) {
            const sc = movie.season_cards.find(c => c.season === targetSeason);
            if (sc) {
                if (sc.poster_url && sc.has_distinct_poster) {
                    movie.poster_url = sc.poster_url;
                    movie.cover_url = sc.poster_url;
                }
                if (sc.overview) {
                    movie.overview = sc.overview;
                    movie.desc = sc.overview;
                }
            }
        }

        return {
          ...movie,
          target_season: targetSeason,
          user_data: { ...(movie.user_data || {}), season: item.season || movie.user_data?.season, episode: item.episode || movie.user_data?.episode, episode_label: item.episode_label || movie.user_data?.episode_label } as any,
          resourceId: item.resource_id, 
          progress: progress,
          duration: duration, 
          time_str: dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          date: dateObj.toLocaleDateString(),
          updated_at: updatedAt
        } as HistoryItem;
      }).sort((a, b) => new Date(b.updated_at!).getTime() - new Date(a.updated_at!).getTime());
    } catch (e) {
      console.warn("History API currently unstable or in 'failed_verification' mode", e);
      return [];
    }
  },

  clearHistory: async (): Promise<{ ok: boolean; msg?: string }> => {
    const res = await fetchApiRaw<unknown>('/v1/user/history', { method: 'DELETE' });
    if (res.ok) return { ok: true };
    return { ok: false, msg: res.msg || `HTTP ${res.status}` };
  },

  deleteHistoryItem: async (resourceId: string): Promise<{ ok: boolean; msg?: string }> => {
    // 后端在记录不存在时回 40401/HTTP 404；从用户视角"那条已经没了" =
    // 删除目标已经达成，UI 也乐观更新过了，按成功处理避免误报错。
    const id = encodeURIComponent(resourceId);
    const res = await fetchApiRaw<unknown>(`/v1/user/history/${id}`, { method: 'DELETE' });
    if (res.ok) return { ok: true };
    if (res.status === 404 || res.code === 40401) return { ok: true };
    return { ok: false, msg: res.msg || `HTTP ${res.status}` };
  },

  reportHistory: async (resourceId: string, positionSec: number, totalDuration: number, sessionId?: string) => {
    try {
      await fetch(`${getApiBase()}/v1/user/history`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resource_id: resourceId,
          position_sec: Math.floor(positionSec),
          total_duration: Math.floor(totalDuration),
          device_id: getDeviceId(),
          device_name: navigator.userAgent,
          ...(sessionId ? { session_id: sessionId } : {})
        })
      });
    } catch (e) { console.error(e); }
  },

  // ─── Favorites ───
  // 后端把收藏做成「用户维度虚拟资源库」：
  //   GET    /api/v1/user/favorites                       → { items: {id, movie_id}[], movie_ids, library }
  //                                                         注意：items 不带完整 movie 详情
  //   GET    /api/v1/user/favorites/{movie_id}            → { movie_id, is_favorite, created_at }
  //   POST   /api/v1/user/favorites/{movie_id}            → 收藏（幂等 newly_added）
  //   DELETE /api/v1/user/favorites/{movie_id}            → 取消（幂等 removed）
  //   GET    /api/v1/libraries/favorites/movies           → 完整 Movie 列表（拿这个做 vault 渲染）
  // 同步副作用：用户首次收藏时 GET /libraries 会出现 id="favorites" 虚拟资源库；
  // 移除最后一个时该虚拟库自动消失。所以收藏后建议 dispatch library-list-dirty
  // 让其他视图刷新。
  getVault: async (): Promise<Movie[]> => {
    try {
      const data = await fetchApi<{ items: ApiMovieSimple[] }>('/v1/libraries/favorites/movies?page_size=200');
      if (!data || !Array.isArray(data.items)) return [];
      return data.items.map(mapApiMovieToUi);
    } catch {
      return [];
    }
  },

  /**
   * 切收藏。先按 isFavorite 决定 method，调成功后返回 is_favorite（后端权威）。
   * 网络/后端 5xx 时 throw，让 UI 层做乐观更新回滚。
   * 后端把收藏挂在 vault 之下：未解锁会 403（业务码 40340），UI 层应区分对待。
   */
  toggleFavorite: async (movie: Movie, isFavorite: boolean): Promise<{ isFavorite: boolean }> => {
    const movieId = encodeURIComponent(String(movie.id));
    const url = `${getApiBase()}/v1/user/favorites/${movieId}`;
    const res = await fetch(url, {
      method: isFavorite ? 'DELETE' : 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const json: any = await res.json().catch(() => ({}));
      if (res.status === 403) {
        throw new VaultError(json?.code, json?.msg, res.status);
      }
      throw new Error(`HTTP ${res.status}`);
    }
    const json: any = await res.json().catch(() => ({}));
    const data = json?.data || {};
    return { isFavorite: !!data.is_favorite };
  },

  isFavorite: async (movieId: string | number): Promise<boolean> => {
    const id = encodeURIComponent(String(movieId));
    const data = await fetchApi<any>(`/v1/user/favorites/${id}`);
    return !!data?.is_favorite;
  },

  // ─── Vault (= Favorites 的访问控制层) ───
  // 后端把"收藏"和"保险库"是同一份数据：要读写收藏（GET/POST/DELETE
  // /user/favorites）必须先在保险库会话里解锁（POST /vault/unlock）。
  // 规则：
  //   - 用户系统关闭时：default 作用域临时视为默认管理员，能看到入口和状态
  //   - 用户系统开启后：只允许已登录管理员访问保险库
  //   - 不论哪种模式都要先设置 6 位 PIN，再用 PIN 解锁会话
  //   - 24h 滚动窗口最多改 10 次 PIN，第 11 次会触发锁定（locked=true）
  // 错误码：403 = 没权限调（普通用户）；423 = locked 状态；400 = PIN 校验失败
  getVaultStatus: async (): Promise<VaultAccessState | null> => {
    return await fetchApi<VaultAccessState>('/v1/user/vault/status');
  },

  setVaultPin: async (req: { newPin: string; currentPin?: string }): Promise<VaultAccessState | null> => {
    try {
      const body: any = { new_pin: req.newPin };
      if (req.currentPin) body.current_pin = req.currentPin;
      const res = await fetch(`${getApiBase()}/v1/user/vault/password`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json: any = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new VaultError(json?.code, json?.msg, res.status);
      }
      return json?.data || null;
    } catch (e) {
      if (e instanceof VaultError) throw e;
      throw new VaultError(undefined, '网络异常', 0);
    }
  },

  unlockVault: async (pin: string): Promise<VaultAccessState | null> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/user/vault/unlock`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      });
      const json: any = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new VaultError(json?.code, json?.msg, res.status);
      }
      return json?.data || null;
    } catch (e) {
      if (e instanceof VaultError) throw e;
      throw new VaultError(undefined, '网络异常', 0);
    }
  },

  lockVault: async (): Promise<VaultAccessState | null> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/user/vault/lock`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      const json: any = await res.json().catch(() => ({}));
      if (!res.ok) return null;
      return json?.data || null;
    } catch {
      return null;
    }
  },

  // ─── Achievements ───
  // 后端契约：
  //   GET  /api/v1/user/achievements           → { defs, user, summary }
  //   POST /api/v1/user/achievements/unlock    → 仅允许 behavior 类，幂等
  // GET 走 fetchApi 拿到的是直接的 data 体（外层 envelope 已被剥），匿名也能拿到 defs；
  // 用户解锁状态后端按 cookie/device_id 识别。
  getAchievements: async (): Promise<{ items: Achievement[]; summary: AchievementSummary | null }> => {
    try {
      const data = await fetchApi<any>('/v1/user/achievements');
      if (!data) return { items: [], summary: null };
      const defs: any[] = Array.isArray(data.defs) ? data.defs : [];
      const userStates: any[] = Array.isArray(data.user) ? data.user : [];
      const stateById = new Map<string, any>();
      for (const u of userStates) {
        if (u && typeof u.id === 'string') stateById.set(u.id, u);
      }
      const items: Achievement[] = defs.map((d: any) => {
        const u = stateById.get(d.id);
        const unlockedAt: string | null = u?.unlocked_at ?? null;
        const unlocked = !!unlockedAt;
        // progress：后端 milestone 给 0..1；behavior 已解锁按 1，未解锁按 0
        const rawProgress = typeof u?.progress === 'number' ? u.progress : null;
        const progress = rawProgress !== null
          ? Math.max(0, Math.min(1, rawProgress))
          : (unlocked ? 1 : 0);
        return {
          id: d.id,
          title: d.title,
          desc: d.desc,
          icon: d.icon,
          category: d.category,
          trigger: d.trigger,
          unlocked,
          unlockedAt,
          progress,
        } as Achievement;
      });
      const s = data.summary || {};
      const summary: AchievementSummary = {
        total: Number(s.total ?? items.length),
        unlocked: Number(s.unlocked ?? items.filter(i => i.unlocked).length),
        milestones: Number(s.milestones ?? 0),
        behaviors: Number(s.behaviors ?? 0),
        newlyUnlockedIds: Array.isArray(s.newly_unlocked_ids) ? s.newly_unlocked_ids : [],
      };
      return { items, summary };
    } catch (e) {
      console.error('getAchievements failed', e);
      return { items: [], summary: null };
    }
  },

  /**
   * 解锁 behavior 类成就。后端幂等，同一 id 重复调用只在首次返回 newly_unlocked=true。
   * 失败/网络异常静默——成就解锁是辅料，不应阻塞主交互。
   * 返回 newly_unlocked 让调用方决定是否弹 toast。
   */
  unlockAchievement: async (id: string): Promise<{ newlyUnlocked: boolean; achievement: Achievement | null }> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/user/achievements/unlock`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, device_id: getDeviceId() }),
      });
      if (!res.ok) return { newlyUnlocked: false, achievement: null };
      const json: any = await res.json().catch(() => null);
      const data = json?.data || {};
      const a = data.achievement || null;
      const ach: Achievement | null = a ? {
        id: a.id,
        title: a.title || '',
        desc: a.desc || '',
        icon: a.icon || '',
        category: a.category || 'behavior',
        trigger: a.trigger,
        unlocked: !!a.unlocked_at,
        unlockedAt: a.unlocked_at ?? null,
        progress: typeof a.progress === 'number' ? a.progress : (a.unlocked_at ? 1 : 0),
      } : null;
      return { newlyUnlocked: !!data.newly_unlocked, achievement: ach };
    } catch (e) {
      console.warn(`unlockAchievement(${id}) failed`, e);
      return { newlyUnlocked: false, achievement: null };
    }
  },
};

/**
 * 解锁 behavior 成就的便捷封装。前端各处埋点统一通过这个入口；
 * 第二个参数控制要不要在 newly_unlocked 时弹 toast 通知用户。
 * 失败永远静默——成就是装饰，不应该让主流程感知。
 */
export async function unlockBehaviorAchievement(id: string, options?: { silent?: boolean }) {
  const { newlyUnlocked, achievement } = await userService.unlockAchievement(id);
  if (newlyUnlocked && achievement && !options?.silent) {
    // 动态拿 toast，避免 user.ts 顶层引入 utils（保持 api 层无 UI 依赖）。
    try {
      const { toast } = await import('../utils');
      toast.success(`🏆 成就解锁：${achievement.title}`);
    } catch { /* noop */ }
  }
  return newlyUnlocked;
}

