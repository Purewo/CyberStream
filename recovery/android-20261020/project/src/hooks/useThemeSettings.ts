import { useState, useEffect } from 'react';
import { THEMES } from '../constants/index';
import { UserSettings } from '../types/index';

export function useThemeSettings() {
  const [settings, setSettings] = useState<UserSettings>(() => {
    try {
        const saved = localStorage.getItem('cyber_settings');
        const parsed = saved ? JSON.parse(saved) : null;
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
          ? { ...parsed, scanlines: typeof parsed.scanlines === 'boolean' ? parsed.scanlines : false, glitch: typeof parsed.glitch === 'boolean' ? parsed.glitch : true }
          : { scanlines: false, glitch: true };
    } catch {
        return { scanlines: false, glitch: true };
    }
  });

  const [themeName, setThemeName] = useState(() => {
    try {
      const saved = localStorage.getItem('cyber_theme');
      return saved && Object.hasOwn(THEMES, saved) ? saved : 'CYBER';
    } catch { return 'CYBER'; }
  });
  const currentTheme = THEMES[themeName] || THEMES.CYBER;

  useEffect(() => {
    try { localStorage.setItem('cyber_settings', JSON.stringify(settings)); } catch { /* storage unavailable */ }
  }, [settings]);

  useEffect(() => {
    try { localStorage.setItem('cyber_theme', themeName); } catch { /* storage unavailable */ }
  }, [themeName]);

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

  return { settings, setSettings, themeName, setThemeName, currentTheme };
}
