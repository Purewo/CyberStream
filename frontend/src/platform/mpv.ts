// PC · libmpv bridge.
//
// Thin wrapper around the Rust commands exposed by pc/src-tauri/src/mpv.rs.
// Player.pc.tsx is the only intended caller; everything else should keep
// using the Web/<video> path so behaviour stays portable.

import type { UnlistenFn } from '@tauri-apps/api/event';

export interface MpvBridge {
  /**
   * Start the mpv subprocess. If `parentHwnd` is supplied, mpv embeds its
   * render surface inside that HWND via `--wid`; otherwise it spawns a
   * standalone window (useful for diagnostics).
   * Returns the pipe name for diagnostics.
   */
  start(parentHwnd?: number): Promise<string>;
  stop(): Promise<void>;
  loadFile(url: string, opts?: { headers?: string[]; start?: number }): Promise<void>;
  setProperty(name: string, value: unknown): Promise<void>;
  getProperty<T = unknown>(name: string): Promise<T>;
  /** Subscribe to a property change. mpv property-change events come back
   *  via `onEvent` with `{ event: 'property-change', name, data: { ... } }`. */
  observeProperty(name: string, id: number): Promise<void>;
  onEvent(handler: (msg: MpvEvent) => void): Promise<UnlistenFn>;
  onExit(handler: () => void): Promise<UnlistenFn>;
}

export interface MpvEvent {
  event: string;
  /** Original mpv message; the property name (when applicable) sits at .name. */
  data: Record<string, unknown>;
}

export async function getMpvBridge(): Promise<MpvBridge> {
  const [{ invoke }, { listen }] = await Promise.all([
    import('@tauri-apps/api/core'),
    import('@tauri-apps/api/event'),
  ]);
  return {
    async start(parentHwnd) {
      return await invoke<string>('mpv_start', { parentHwnd: parentHwnd ?? null });
    },
    async stop() {
      await invoke('mpv_stop');
    },
    async loadFile(url, opts) {
      await invoke('mpv_load_file', {
        url,
        headers: opts?.headers ?? null,
        start: opts?.start ?? null,
      });
    },
    async setProperty(name, value) {
      await invoke('mpv_set_property', { name, value });
    },
    async getProperty<T = unknown>(name: string) {
      return (await invoke<T>('mpv_get_property', { name })) as T;
    },
    async observeProperty(name, id) {
      await invoke('mpv_observe_property', { name, id });
    },
    async onEvent(handler) {
      return await listen<MpvEvent>('mpv:event', (e) => handler(e.payload));
    },
    async onExit(handler) {
      return await listen('mpv:exit', () => handler());
    },
  };
}
