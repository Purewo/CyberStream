# CyberStream PC client

Tauri (Rust + WebView2) shell that wraps the React frontend and embeds libmpv
for hardware-accelerated playback. Backend continues to run on your NAS or
home server — this client never bundles it.

> Status: **M0 — Tauri skeleton + mpv IPC self-test** (1.21.0-pc.M0)
> Tracking doc: [docs/PC_CLIENT_GOAL.md](../docs/PC_CLIENT_GOAL.md)

---

## Layout

```
pc/
├── src-tauri/      Rust shell (Tauri 2)
├── scripts/        Node helpers (e.g. mpv IPC self-test)
└── vendor/         Third-party binaries (NOT in git — see below)
    └── mpv/        mpv.exe + d3dcompiler_43.dll (Windows)
```

`pc/vendor/` is gitignored. Each developer fetches the binaries locally; the
final installer bundles them via `bundle.resources` in `tauri.conf.json`.

---

## Prerequisites

- **Windows 11** (24H2 or newer recommended)
- **Node.js 22+** for the React frontend
- **Rust 1.77+** (`rustup`) — installs `cargo`, `rustc` you already have if
  you set up Tauri before
- **WebView2 Runtime** — preinstalled on Windows 11
- **`cargo-tauri`** — `cargo install tauri-cli --version "^2.0" --locked`

---

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

The IPC self-test spawns mpv with `--input-ipc-server`, queries a few
properties (`mpv-version`, `ffmpeg-version`, `platform`), and exits 0 on
success.

---

## Run in dev mode

```bash
cd pc/src-tauri
cargo tauri dev
```

This launches Vite on port 3000 (via `beforeDevCommand`), waits for it, then
opens the Tauri window pointing at `http://localhost:3000`. Hot reload works
the same as the pure-web flow.

> If port 3000 is already taken (e.g. you also have `npm run dev` running in
> another shell), kill the other process first — Tauri does not currently fall
> back to a different port.

---

## Build a release (M5 onwards)

```bash
cd pc/src-tauri
cargo tauri build
```

Output goes to `pc/src-tauri/target/release/bundle/`:
- `msi/CyberStream_1.21.0_x64_en-US.msi`
- `nsis/CyberStream_1.21.0_x64-setup.exe`

Both bundle `pc/vendor/mpv/mpv.exe` as a resource. **Do not** ship the
unsigned installer to end users yet — Windows SmartScreen will block it. v1
ships unsigned with a setup-doc workaround; signing comes later.

---

## What's wired so far (M0)

- Tauri 2 shell with Shell, Dialog, Store, Clipboard plugins enabled
- Single window (1440x900, min 1024x640) loading the existing React SPA
- One Rust command: `ping()` returns `CARGO_PKG_VERSION` for adapter sanity
  check (consumed by `frontend/src/platform/pc.ts` once that lands in M1)
- Icon set generated from a placeholder seed (replace with real artwork
  before M5)

## What's next

See [`docs/PC_CLIENT_GOAL.md`](../docs/PC_CLIENT_GOAL.md). M1 introduces the
platform adapter (`frontend/src/platform/`); M3 swaps the in-page `<video>`
for libmpv child windows controlled over IPC; M4 polishes hotkeys + GPU
status; M5 ships an installer.
