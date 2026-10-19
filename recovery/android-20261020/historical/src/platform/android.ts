import { Capacitor } from '@capacitor/core';
import { API_BASE } from '../constants';
import { openAndroidExternalUrl } from './androidPlayer';
import type { Platform, PlatformStorage } from './index';

const androidStorage: PlatformStorage = {
  get(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* quota / disabled */ }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch { /* noop */ }
  },
};

function publicOrigin(apiBase: string): string {
  try {
    const url = new URL(apiBase);
    return `${url.protocol}//${url.host}`;
  } catch {
    return '';
  }
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const input = document.createElement('textarea');
  input.value = text;
  input.style.position = 'fixed';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  try { document.execCommand('copy'); } finally { document.body.removeChild(input); }
}

export function createAndroidPlatform(): Platform {
  return {
    kind: 'android',
    storage: androidStorage,
    getApiBase: () => API_BASE,
    // Capacitor's WebView origin is https://localhost. Shared links must
    // instead use the hosted API origin users can actually reach.
    getPublicUrlBase: () => publicOrigin(API_BASE),
    async shellOpen(url) {
      try {
        if (Capacitor.isPluginAvailable('CyberPlayer')) {
          await openAndroidExternalUrl(url);
          return;
        }
      } catch (error) {
        console.warn('[android] external intent failed, falling back to WebView', error);
      }
      window.open(url, '_blank', 'noopener,noreferrer');
    },
    writeClipboard: copyText,
    async toggleFullscreen() {
      const doc = document as Document & {
        webkitFullscreenElement?: Element;
        webkitExitFullscreen?: () => Promise<void>;
      };
      const root = document.documentElement as HTMLElement & {
        webkitRequestFullscreen?: () => Promise<void>;
      };
      if (doc.fullscreenElement || doc.webkitFullscreenElement) {
        if (doc.exitFullscreen) await doc.exitFullscreen();
        else if (doc.webkitExitFullscreen) await doc.webkitExitFullscreen();
      } else if (root.requestFullscreen) {
        await root.requestFullscreen();
      } else if (root.webkitRequestFullscreen) {
        await root.webkitRequestFullscreen();
      }
    },
    async isFullscreen() {
      const doc = document as Document & { webkitFullscreenElement?: Element };
      return !!(doc.fullscreenElement || doc.webkitFullscreenElement);
    },
  };
}
