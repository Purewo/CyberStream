import { useState, useEffect, useRef } from 'react';
import { THEMES } from '../constants/index';
import { UserSettings } from '../types/index';
import { userService } from '../api';

const LS_KEY = 'cyber_settings';
const LS_THEME_KEY = 'cyber_theme';
const DEFAULT_SETTINGS: UserSettings = { scanlines: false, glitch: true };

function readLocalSettings(): UserSettings {
  try {
    const saved = localStorage.getItem(LS_KEY);
    return saved ? JSON.parse(saved) : { ...DEFAULT_SETTINGS };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function readLocalTheme(): string {
  try {
    return localStorage.getItem(LS_THEME_KEY) || 'CYBER';
  } catch {
    return 'CYBER';
  }
}

/**
 * 主题 / 视觉特效 / 个人偏好的状态源。
 *
 * 持久化分两层：
 *   1. localStorage —— 同步、离线、首屏不闪烁的本地缓存（始终写）。
 *   2. 后端 /user/preferences —— 绑当前登录账号，换设备不丢（登录态下读+回写）。
 *
 * 顺序：初始用 localStorage 立即渲染；登录后 GET 后端覆盖；之后任何变更
 * debounce PUT 回后端并同步写 localStorage。未登录 / 单 token 模式下后端
 * 失败静默，纯本地工作（行为同改造前）。
 */
export function useThemeSettings(authenticated?: boolean) {
  const [settings, setSettings] = useState<UserSettings>(() => readLocalSettings());
  const [themeName, setThemeName] = useState<string>(() => readLocalTheme());
  const currentTheme = THEMES[themeName] || THEMES['CYBER'];

  // 标记后端偏好是否已加载完成；加载阶段不要把本地值反向 PUT 覆盖后端。
  const hydratedRef = useRef(false);
  const putTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 本地缓存：始终随状态写 localStorage（离线 / 未登录也能记住）。
  useEffect(() => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(settings)); } catch { /* quota / SSR */ }
  }, [settings]);
  useEffect(() => {
    try { localStorage.setItem(LS_THEME_KEY, themeName); } catch { /* quota / SSR */ }
  }, [themeName]);

  // 应用 CSS 变量（主题色 + 特效开关）。
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--scanline-opacity', settings.scanlines ? '0.2' : '0');
    root.style.setProperty('--scanline-display', settings.scanlines ? 'block' : 'none');
    root.style.setProperty('--glitch-active', settings.glitch ? 'block' : 'none');
    root.style.setProperty('--color-primary', currentTheme.primary);
    root.style.setProperty('--color-secondary', currentTheme.secondary);
    root.style.setProperty('--color-bg', currentTheme.bg);
    root.style.setProperty('--color-text', currentTheme.text);
    root.style.setProperty('--color-accent', currentTheme.accent);
  }, [settings, currentTheme]);

  // 登录态变化时从后端拉偏好覆盖本地。authenticated 为 undefined（单 token /
  // 未启用用户系统）时也尝试一次——后端没接口或 401 会静默返回 null，不影响本地。
  useEffect(() => {
    if (authenticated === false) {
      // 明确未登录：不拉后端，保持本地缓存即可。
      hydratedRef.current = true;
      return;
    }
    let active = true;
    (async () => {
      const remote = await userService.getPreferences();
      if (!active) {
        hydratedRef.current = true;
        return;
      }
      if (remote && typeof remote === 'object') {
        const { theme, scanlines, glitch, homepage } = remote as any;
        setSettings(prev => ({
          ...prev,
          ...(typeof scanlines === 'boolean' ? { scanlines } : {}),
          ...(typeof glitch === 'boolean' ? { glitch } : {}),
          ...(homepage ? { homepage } : {}),
        }));
        if (typeof theme === 'string' && THEMES[theme]) setThemeName(theme);
      }
      hydratedRef.current = true;
    })();
    return () => { active = false; };
  }, [authenticated]);

  // 任意偏好变更 → debounce 回写后端（仅在已 hydrate 后，避免加载期把旧本地值
  // 覆盖刚拉到的后端值）。未登录 / 无接口时 PUT 静默失败，不影响本地缓存。
  useEffect(() => {
    if (!hydratedRef.current) return;
    if (authenticated === false) return;
    if (putTimer.current) clearTimeout(putTimer.current);
    putTimer.current = setTimeout(() => {
      void userService.putPreferences({
        theme: themeName,
        scanlines: settings.scanlines,
        glitch: settings.glitch,
        homepage: settings.homepage || {},
      });
    }, 600);
    return () => { if (putTimer.current) clearTimeout(putTimer.current); };
  }, [settings, themeName, authenticated]);

  return { settings, setSettings, themeName, setThemeName, currentTheme };
}

