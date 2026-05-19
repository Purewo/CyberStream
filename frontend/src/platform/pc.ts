// CyberStream platform adapter · PC (Tauri) implementation.
//
// Talks to the Rust shell over Tauri commands and plugin APIs. We import the
// plugin namespaces lazily (via top-level `import type` plus `import()` at
// call sites) so the web bundle still tree-shakes them out — Vite ignores
// dynamic imports that no caller reaches.

import { API_BASE } from '../constants';
import type { Platform, PlatformStorage } from './index';

const STORAGE_KEYS = {
  apiBase: 'cyber_pc_api_base',
} as const;

// In-memory cache backed by localStorage. The Tauri webview's localStorage is
// scoped to the app data directory, so values survive across launches without
// us having to plumb tauri-plugin-store for the M1 baseline. We can graduate
// to plugin-store when we add cross-machine sync (post v1).
const pcStorage: PlatformStorage = {
  get(key) {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* noop */ }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch { /* noop */ }
  },
};

function readApiBase(): string {
  return pcStorage.get(STORAGE_KEYS.apiBase) || API_BASE;
}

function derivePublicBase(apiBase: string): string {
  // apiBase ends in `/api`; the public site lives one level above.
  try {
    const u = new URL(apiBase);
    return `${u.protocol}//${u.host}`;
  } catch {
    return '';
  }
}

export function createPcPlatform(): Platform {
  return {
    kind: 'pc',
    storage: pcStorage,
    getApiBase: () => readApiBase(),
    getPublicUrlBase: () => derivePublicBase(readApiBase()),
    async shellOpen(url) {
      const { open } = await import('@tauri-apps/plugin-shell');
      await open(url);
    },
    async writeClipboard(text) {
      const { writeText } = await import('@tauri-apps/plugin-clipboard-manager');
      await writeText(text);
    },
    async toggleFullscreen() {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      const win = getCurrentWindow();
      const fs = await win.isFullscreen();
      await win.setFullscreen(!fs);
    },
    async isFullscreen() {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      return await getCurrentWindow().isFullscreen();
    },
  };
}

/**
 * Update the persisted backend URL. Used by the M2 settings panel; exported
 * here (rather than on the Platform interface) because only PC has a
 * configurable backend — the Web build's API_BASE is baked in at build time.
 */
export function setApiBase(value: string): void {
  pcStorage.set(STORAGE_KEYS.apiBase, value.replace(/\/+$/, ''));
}
