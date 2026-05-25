// CyberStream platform adapter · PC (Tauri) implementation.
//
// Talks to the Rust shell over Tauri commands and plugin APIs. We import the
// plugin namespaces lazily (via top-level `import type` plus `import()` at
// call sites) so the web bundle still tree-shakes them out — Vite ignores
// dynamic imports that no caller reaches.

import type { Platform, PlatformStorage } from './index';

const STORAGE_KEYS = {
  apiBase: 'cyber_pc_api_base',
} as const;

/**
 * 桌面默认后端：测试期回到 https://pw.pioneer.fan:84/api（IPv6，TLS）。
 * 用户在「设置 → 后端服务器」填过的 localStorage 覆盖值优先生效；改默认
 * 不会动用户已配置的地址。
 *
 * full 包带 sidecar 的场景需要在 Rust 那边监听 sidecar 起来后写入
 * localStorage 把这里覆盖掉。
 */
const PC_DEFAULT_API_BASE = 'https://pw.pioneer.fan:84/api';

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
  return pcStorage.get(STORAGE_KEYS.apiBase) || PC_DEFAULT_API_BASE;
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

// ─── Proxy settings ───
//
// 两类代理（独立配置）：
//   - app_proxy: API + 静态资源。同时作用于 WebView2 和 Rust reqwest。
//     WebView2 的 --proxy-server 只在进程启动时读，**改完必须重启**。
//   - video_proxy: mpv 视频流。运行时变更对下一次播放即时生效。
//
// 持久化由 Rust 那边写入 %APPDATA%\com.purewo.cyberstream\proxy.json，
// 避免 WebView2 的 catch-22（启动期 localStorage 还没就绪，不能用来决定
// --proxy-server）。前端进设置面板时 invoke 拉一次最新值。

export interface ProxyConfig {
  app_proxy: string | null;
  video_proxy: string | null;
}

export async function getProxyConfig(): Promise<ProxyConfig> {
  const { invoke } = await import('@tauri-apps/api/core');
  const cfg = await invoke<ProxyConfig | null>('get_proxy_config');
  return {
    app_proxy: cfg?.app_proxy ?? null,
    video_proxy: cfg?.video_proxy ?? null,
  };
}

export async function setProxyConfig(cfg: ProxyConfig): Promise<ProxyConfig> {
  const { invoke } = await import('@tauri-apps/api/core');
  const next = await invoke<ProxyConfig>('set_proxy_config', {
    appProxy: cfg.app_proxy,
    videoProxy: cfg.video_proxy,
  });
  return {
    app_proxy: next?.app_proxy ?? null,
    video_proxy: next?.video_proxy ?? null,
  };
}
