# CyberStream PC client

Tauri (Rust + WebView2) shell that wraps the React frontend and embeds libmpv
for hardware-accelerated playback. Backend continues to run on your NAS or
home server — this client never bundles it.

> Status: **1.21.0-pc.0 — first installable build**
> Tracking doc: [docs/PC_CLIENT_GOAL.md](../docs/PC_CLIENT_GOAL.md)

---

## What you get in 1.21.0-pc.0

| Capability | State |
|---|---|
| Bundled installer | MSI (~50 MB, includes mpv runtime) |
| External player handoff | PotPlayer / VLC / IINA / nPlayer / MX / Infuse — all routed through Tauri shell, zero browser blocking |
| Backend URL config | Profile → SYSTEM → 后端服务器 (persists, no rebuild needed) |
| F11 fullscreen + Esc exit | Window-level fullscreen; whole UI maximizes, not just the video |
| Same React UI as Web | 100% feature parity with the web build at 1.21.0 |
| libmpv bridge | Rust IPC bridge present, self-test in 设置 → 后端服务器. Player.tsx integration deferred to a follow-up — for now use external player handoff for true 4K REMUX / DV playback |
| Code signing | Not yet — Windows SmartScreen will warn; click "More info → Run anyway" |

---

## Layout

```
pc/
├── src-tauri/      Rust shell (Tauri 2)
├── scripts/        Node helpers (mpv IPC self-test)
└── vendor/         Third-party binaries (NOT in git)
    └── mpv/        mpv.exe + d3dcompiler_43.dll (Windows)
```

`pc/vendor/` is gitignored. Each developer fetches the binaries locally; the
final installer bundles them via `bundle.resources` in `tauri.conf.json`.

---

## Prerequisites (build from source)

- **Windows 11** (24H2 or newer recommended)
- **Node.js 22+** for the React frontend
- **Rust 1.77+** (`rustup`)
- **WebView2 Runtime** — preinstalled on Windows 11
- **`cargo-tauri`** — `cargo install tauri-cli --version "^2.0" --locked`

## First-time setup

```bash
# 1. install frontend deps (in repo root)
cd frontend
npm install
cd ..

# 2. drop the mpv windows build into pc/vendor/mpv/
#    Source: https://github.com/shinchiro/mpv-winbuild-cmake/releases (x86_64 .7z)
#    Extract so the layout is:
#      pc/vendor/mpv/mpv.exe
#      pc/vendor/mpv/d3dcompiler_43.dll
#      pc/vendor/mpv/...

# 3. quick smoke test of the mpv IPC bridge
node pc/scripts/verify_mpv_ipc.mjs
```

## Run in dev mode

```bash
cd pc/src-tauri
cargo tauri dev
```

Vite serves on port 3000; Tauri opens a window pointed at it. Hot reload
works the same as the pure-web flow.

## Build the MSI

```bash
cd pc/src-tauri
cargo tauri build
```

Output: `pc/src-tauri/target/release/bundle/msi/CyberStream_1.21.0_x64_en-US.msi`.

The MSI bundles `pc/vendor/mpv/*` as resources. Install on a fresh machine
to verify everything wired up.

NSIS is deferred — the Tauri toolchain pulls nsis-3.11.zip from GitHub at
build time and times out from regional networks. Re-enable in
`tauri.conf.json` (`bundle.targets`) if your network allows it.

---

## Known gaps (will iterate post-pc.0)

- **libmpv embedding** — the Rust bridge spawns mpv on demand and the IPC
  protocol is wired up, but Player.tsx still drives the in-page `<video>`
  element. For 4K HEVC / Dolby Vision today, prefer the external-player
  handoff (PotPlayer / VLC / IINA buttons on the movie detail page) which
  goes through `tauri-plugin-shell` and bypasses any browser decoder
  limits.
- **Code signing** — unsigned MSI will trigger SmartScreen.
- **No auto-update** — pull a fresh MSI from Releases manually for now.
- **Windows only** — macOS / Linux ports follow once the Win build
  stabilizes.
