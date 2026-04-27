import { ThemeConfig, UserSettings } from './types';

export const formatBytes = (bytes: string | number | undefined, decimals = 2) => {
  if (bytes === 0 || bytes === '0') return '0 Bytes';
  if (!bytes) return 'Unknown';
  const b = typeof bytes === 'string' ? parseInt(bytes, 10) : bytes;
  if (isNaN(b)) return '0 Bytes';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(b) / Math.log(k));
  return parseFloat((b / Math.pow(k, i)).toFixed(dm)) + ' ' + (sizes[i] || 'Bytes');
};

export const formatDuration = (seconds: number | undefined) => {
  if (!seconds) return "00:00";
  const sec = seconds; // Assuming seconds is already a number
  if (isNaN(sec)) return "00:00";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}:${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  return `${m}:${s < 10 ? '0' : ''}${s}`;
};

export const getStyles = (settings: UserSettings, currentTheme: ThemeConfig) => ` 
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&display=swap'); 
  :root { --color-primary: ${currentTheme.primary}; --color-secondary: ${currentTheme.secondary}; --color-bg: ${currentTheme.bg}; --color-text: ${currentTheme.text}; --color-accent: ${currentTheme.accent}; --scanline-opacity: ${settings.scanlines ? 0.15 : 0}; --scanline-display: ${settings.scanlines ? 'block' : 'none'}; --glitch-active: ${settings.glitch ? 'block' : 'none'}; } 
  .text-primary { color: var(--color-primary); } .text-secondary { color: var(--color-secondary); } .text-accent { color: var(--color-accent); } 
  .text-primary-70 { color: color-mix(in srgb, var(--color-primary) 70%, transparent); }
  .bg-primary { background-color: var(--color-primary); } .border-primary { border-color: var(--color-primary); } 
  .bg-primary-5 { background-color: color-mix(in srgb, var(--color-primary) 5%, transparent); }
  .bg-primary-10 { background-color: color-mix(in srgb, var(--color-primary) 10%, transparent); }
  .bg-primary-20 { background-color: color-mix(in srgb, var(--color-primary) 20%, transparent); }
  .border-primary-30 { border-color: color-mix(in srgb, var(--color-primary) 30%, transparent); }
  .border-primary-50 { border-color: color-mix(in srgb, var(--color-primary) 50%, transparent); }
  ::-webkit-scrollbar { width: 6px; height: 6px; } ::-webkit-scrollbar-track { background: #0a0a12; } ::-webkit-scrollbar-thumb { background: #333; } ::-webkit-scrollbar-thumb:hover { background: var(--color-primary); } 
  input[type=range] { -webkit-appearance: none; background: transparent; } input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; height: 12px; width: 12px; border-radius: 50%; background: var(--color-primary); cursor: pointer; margin-top: -5px; box-shadow: 0 0 10px var(--color-primary); } input[type=range]::-webkit-slider-runnable-track { width: 100%; height: 2px; cursor: pointer; background: #333; border-radius: 1.3px; } 
  .scanlines { background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,0) 50%, rgba(0,0,0,var(--scanline-opacity)) 50%, rgba(0,0,0,var(--scanline-opacity))); background-size: 100% 4px; position: fixed; top: 0; right: 0; bottom: 0; left: 0; z-index: 50; pointer-events: none; display: var(--scanline-display, none); } 
  .glitch-text { position: relative; } .glitch-text::before, .glitch-text::after { content: attr(data-text); position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: var(--glitch-active); } .glitch-text::before { left: 2px; text-shadow: -1px 0 var(--color-accent); clip: rect(44px, 450px, 56px, 0); animation: glitch-anim 5s infinite linear alternate-reverse; } .glitch-text::after { left: -2px; text-shadow: -1px 0 var(--color-primary); clip: rect(44px, 450px, 56px, 0); animation: glitch-anim2 5s infinite linear alternate-reverse; } 
  @keyframes glitch-anim { 0% { clip: rect(35px, 9999px, 36px, 0); } 20% { clip: rect(8px, 9999px, 99px, 0); } 40% { clip: rect(68px, 9999px, 1px, 0); } 60% { clip: rect(26px, 9999px, 67px, 0); } 80% { clip: rect(9px, 9999px, 34px, 0); } 100% { clip: rect(58px, 9999px, 86px, 0); } } 
  @keyframes glitch-anim2 { 0% { clip: rect(65px, 9999px, 100px, 0); } 20% { clip: rect(52px, 9999px, 1px, 0); } 40% { clip: rect(14px, 9999px, 61px, 0); } 60% { clip: rect(33px, 9999px, 77px, 0); } 80% { clip: rect(12px, 9999px, 99px, 0); } 100% { clip: rect(82px, 9999px, 10px, 0); } } 
  .perspective-grid { position: absolute; width: 200%; height: 130%; bottom: -30%; left: -50%; background-image: linear-gradient(to right, rgba(0, 243, 255, 0.05) 1px, transparent 1px), linear-gradient(to bottom, rgba(188, 19, 254, 0.05) 1px, transparent 1px); background-size: 50px 50px; transform: perspective(500px) rotateX(60deg); animation: grid-move 20s linear infinite; z-index: 0; pointer-events: none; } 
  @keyframes grid-move { 0% { transform: perspective(500px) rotateX(60deg) translateY(0); } 100% { transform: perspective(500px) rotateX(60deg) translateY(50px); } } 
  .no-scrollbar::-webkit-scrollbar { display: none; } .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; } 
  .tech-border { position: relative; } .tech-border::before { content: ''; position: absolute; top: 0; left: 0; width: 10px; height: 10px; border-top: 2px solid var(--color-primary); border-left: 2px solid var(--color-primary); } .tech-border::after { content: ''; position: absolute; bottom: 0; right: 0; width: 10px; height: 10px; border-bottom: 2px solid var(--color-primary); border-right: 2px solid var(--color-primary); } 
  .text-shadow-neon { text-shadow: 0 0 10px var(--color-primary); } .box-shadow-neon { box-shadow: 0 0 15px var(--color-primary); } .clip-corner { clip-path: polygon(0 0, 100% 0, 100% 85%, 95% 100%, 0 100%); } 
`;


export type ToastType = 'success' | 'error' | 'info' | 'warning';

const emitToast = (message: string, type: ToastType = 'info', duration: number = 3000) => {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('cyber:toast', {
      detail: { message, type, duration }
    }));
  }
};

export const toast = {
  success: (msg: string, dur?: number) => emitToast(msg, 'success', dur),
  error: (msg: string, dur?: number) => emitToast(msg, 'error', dur),
  info: (msg: string, dur?: number) => emitToast(msg, 'info', dur),
  warning: (msg: string, dur?: number) => emitToast(msg, 'warning', dur)
};
