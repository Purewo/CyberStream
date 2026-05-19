// CyberStream platform adapter — public contract.
//
// The same React code runs in two runtimes:
//   - Web: standard browser APIs (default).
//   - PC: Tauri 2 webview with native bridges (mpv, shell, store, dialog).
//
// Differences are funneled through this module so feature code never has to
// know which runtime it's in. Always import from `../platform` (or `./platform`),
// never from the runtime-specific implementations.

import { createWebPlatform } from './web';
import { createPcPlatform } from './pc';

export interface Platform {
  /** Stable identifier of the runtime — useful for telemetry / debug overlays. */
  readonly kind: 'web' | 'pc';

  /**
   * Backend base URL used by api/core.ts. Defaults to the constants value on
   * Web; on PC this is read from tauri-store and configurable in settings.
   */
  getApiBase(): string;

  /**
   * Public-facing URL prefix used to build shareable links (`/movie/{id}`).
   * On Web this is `window.location.origin`. On PC the webview origin is
   * `tauri.localhost`, so we derive a public origin from `getApiBase()` (or
   * fall back to an empty string when no public host is set).
   */
  getPublicUrlBase(): string;

  /** Persistent, namespaced key/value store. Synchronous in both runtimes. */
  readonly storage: PlatformStorage;

  /**
   * Open a URL with the OS's protocol handler. On Web this is
   * `window.open(url, '_blank')`; on PC it routes through the Tauri shell
   * plugin so that `vlc://`, `potplayer://`, etc. dispatch to native apps
   * instead of being blocked by the webview.
   */
  shellOpen(url: string): Promise<void>;

  /** Write plain text to the system clipboard. */
  writeClipboard(text: string): Promise<void>;
}

export interface PlatformStorage {
  get(key: string): string | null;
  set(key: string, value: string): void;
  remove(key: string): void;
}

/**
 * Detects the runtime once at first call.
 *
 * Tauri injects `__TAURI_INTERNALS__` (Tauri 2) onto the window before app
 * code runs; older builds also expose `__TAURI__`. We probe both to stay
 * forward-compatible.
 */
function detectKind(): 'web' | 'pc' {
  const w = globalThis as { __TAURI_INTERNALS__?: unknown; __TAURI__?: unknown };
  return w.__TAURI_INTERNALS__ || w.__TAURI__ ? 'pc' : 'web';
}

let cached: Platform | null = null;

export function platform(): Platform {
  if (!cached) {
    cached = detectKind() === 'pc' ? createPcPlatform() : createWebPlatform();
  }
  return cached;
}

// Convenience re-exports — most callers just need these.
export const getApiBase = (): string => platform().getApiBase();
export const getPublicUrlBase = (): string => platform().getPublicUrlBase();
export const shellOpen = (url: string): Promise<void> => platform().shellOpen(url);
export const writeClipboard = (text: string): Promise<void> => platform().writeClipboard(text);
export const storage = (): PlatformStorage => platform().storage;
