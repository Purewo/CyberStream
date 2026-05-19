// CyberStream platform adapter · Web implementation.
//
// Plain browser APIs. No Tauri imports here — keeping this file independent
// also lets it run in older browsers without dynamic import shims.

import { API_BASE } from '../constants';
import type { Platform, PlatformStorage } from './index';

const webStorage: PlatformStorage = {
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

export function createWebPlatform(): Platform {
  return {
    kind: 'web',
    storage: webStorage,
    getApiBase: () => API_BASE,
    getPublicUrlBase: () => {
      try { return window.location.origin; }
      catch { return ''; }
    },
    async shellOpen(url) {
      // window.open is blocked when called outside a user gesture, but every
      // existing call site is wired to a click handler. We deliberately do
      // not fall back to location.href to keep behavior predictable inside
      // iframes and embedded contexts.
      window.open(url, '_blank', 'noopener,noreferrer');
    },
    async writeClipboard(text) {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      // Fallback for non-secure contexts (HTTP without TLS) where the
      // Clipboard API is unavailable. Uses a hidden textarea + execCommand.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } finally { document.body.removeChild(ta); }
    },
    async toggleFullscreen() {
      const doc = document as Document & {
        webkitFullscreenElement?: Element;
        webkitExitFullscreen?: () => Promise<void>;
      };
      const root = document.documentElement as HTMLElement & {
        webkitRequestFullscreen?: () => Promise<void>;
      };
      const inFs = !!(doc.fullscreenElement || doc.webkitFullscreenElement);
      if (inFs) {
        if (doc.exitFullscreen) await doc.exitFullscreen();
        else if (doc.webkitExitFullscreen) await doc.webkitExitFullscreen();
      } else {
        if (root.requestFullscreen) await root.requestFullscreen();
        else if (root.webkitRequestFullscreen) await root.webkitRequestFullscreen();
      }
    },
    async isFullscreen() {
      const doc = document as Document & { webkitFullscreenElement?: Element };
      return !!(doc.fullscreenElement || doc.webkitFullscreenElement);
    },
  };
}
