# CyberStream PC 1.21.0-pc.0

First installable build of the CyberStream PC client.

## Download

- `CyberStream_1.21.0_x64_en-US.msi` — Windows 11 x64

The installer bundles the mpv runtime, so you don't need to install mpv
separately. Backend (Flask) still runs on your NAS or home server — this
client only replaces the browser/frontend half.

> **SmartScreen warning:** The MSI is unsigned. Click *More info → Run anyway*.
> Code signing is on the post-pc.0 list.

## What's inside

- Tauri 2 shell + WebView2, single window, full feature parity with the
  web build at 1.21.0.
- External-player handoff: PotPlayer / VLC / IINA / nPlayer / MX Player /
  MX Player Pro / Infuse — routed through `tauri-plugin-shell` so the OS
  protocol handler dispatches them correctly. No more browser blocking on
  `vlc://` / `iina://`.
- Backend URL configurable in Profile → SYSTEM → 后端服务器. Persists
  across launches.
- F11 toggles window fullscreen; Esc exits.
- libmpv bridge ready (Rust IPC + Tauri commands + frontend adapter).
  Self-test in the same settings card.

## Known limitations

- **libmpv is not yet driving Player.tsx** — the bridge is wired, but the
  in-page `<video>` element still handles playback. For 4K HEVC REMUX,
  Dolby Vision Profile 5, and TrueHD/Atmos pass-through, use the external
  player handoff buttons on the movie detail page. The web `<video>` path
  remains unchanged from 1.21.0.
- Unsigned installer, no auto-updater.
- macOS / Linux: not yet.

## Verifying after install

1. Open CyberStream.
2. Confirm Profile → SYSTEM → 后端服务器 shows the right backend URL,
   change if needed.
3. Click *运行检测* in the same card. Expect `OK · mpv vX.Y.Z · pipe=…`.
4. Open any movie, try one of the external-player icons. Your local
   PotPlayer / IINA / VLC should launch without prompts.

## Source

- Tag: `v1.21.0-pc.0`
- Tracking doc: [docs/PC_CLIENT_GOAL.md](docs/PC_CLIENT_GOAL.md)
- Build instructions: [pc/README.md](pc/README.md)
