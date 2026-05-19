import { useState, useEffect } from 'react';
import { THEMES } from '../constants/index';
import { UserSettings } from '../types/index';

export function useThemeSettings() {
  const [settings, setSettings] = useState<UserSettings>(() => {
    try {
        const saved = localStorage.getItem('cyber_settings');
        return saved ? JSON.parse(saved) : { scanlines: false, glitch: true };
    } catch {
        return { scanlines: false, glitch: true };
    }
  });

  const [themeName, setThemeName] = useState('CYBER'); 
  const currentTheme = THEMES[themeName]; 

  useEffect(() => {
    localStorage.setItem('cyber_settings', JSON.stringify(settings));
  }, [settings]);

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
