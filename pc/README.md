# CyberStream PC client

Tauri (Rust + WebView2) shell that wraps the React frontend and embeds libmpv
for hardware-accelerated playback. Backend continues to run on your NAS or
home server — this client never bundles it.

> Status: **1.21.1 — native player + external handoff with subtitles**
> Tracking doc: [docs/PC_CLIENT_GOAL.md](../docs/PC_CLIENT_GOAL.md)

---

## What you get in 1.21.1

| Capability | State |
|---|---|
| Bundled installer | MSI (~93 MB, includes mpv runtime + native player) |
| Native player | Win32 + libmpv + egui HUD; 4K HEVC / Dolby Vision / TrueHD pass-through; per-season picker; in-window subtitle search/bind/preview; Rust-side history heartbeat |
| External player handoff | PotPlayer / VLC: native `.exe` spawn with default subtitle pre-loaded (Windows registry + Program Files lookup, falls back to URL scheme on miss). IINA / nPlayer / MX / Infuse: URL scheme |
| Backend URL config | Profile → SYSTEM → 后端服务器 (persists, no rebuild) |
| F11 fullscreen + Esc exit | Window-level fullscreen everywhere; native player has its own Esc-twice-quit |
| Same React UI as Web | 100% feature parity with the web build at 1.21.1 |
| Code signing | Not yet — Windows SmartScreen will warn; click "More info → Run anyway" |

---

## Layout

```
pc/
├── src-tauri/      Rust shell (Tauri 2)
│   └── src/
│       ├── lib.rs              entry, command registration
│       ├── external_player.rs  PotPlayer / VLC native launch
│       └── native_player/      libmpv + egui HUD player window
├── scripts/        Node helpers
└── vendor/         Third-party binaries (NOT in git)
    └── mpv/        libmpv runtime (Windows)
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

# 2. drop the libmpv windows build into pc/vendor/mpv/
#    Source: https://github.com/shinchiro/mpv-winbuild-cmake/releases (x86_64 .7z)
#    The native player loads libmpv via FFI; you need libmpv-2.dll + d3dcompiler_47.dll.
#    Layout:
#      pc/vendor/mpv/libmpv-2.dll
#      pc/vendor/mpv/d3dcompiler_47.dll
#      pc/vendor/mpv/...
```

## Run in dev mode

```bash
cd pc/src-tauri
cargo tauri dev
```

Vite serves on port 3000; Tauri opens a window pointed at it. Hot reload
works the same as the pure-web flow. Click any 播放 button on a movie detail
page to spawn the native player window (Esc twice to exit).

## Build the MSI

```bash
cd pc/src-tauri
cargo tauri build
```

Output: `pc/src-tauri/target/release/bundle/msi/CyberStream_1.21.1_x64_en-US.msi`.

The MSI bundles `pc/vendor/mpv/*` as resources. Install on a fresh machine
to verify everything wired up.

NSIS is deferred — the Tauri toolchain pulls nsis-3.11.zip from GitHub at
build time and times out from regional networks. Re-enable in
`tauri.conf.json` (`bundle.targets`) if your network allows it.

---

## External player notes (1.21.1)

The PotPlayer / VLC buttons on the movie detail page now spawn the native
`.exe` directly (instead of using the OS URL handler), so we can:

- Pass the default subtitle URL via CLI
- Avoid `potplayer://` query-string truncation issues
- Detach the spawned process from CyberStream's lifetime

PotPlayer needs `/current` to reuse an existing window (otherwise launching
twice produces two processes that both grab the GL/audio device → black
screen). VLC uses `:sub-file=<path>` MRL options because the global
`--sub-file=` flag in 3.x has a known bug with HTTP URLs.

Subtitle URLs are downloaded to `%TEMP%\cyberstream_sub_<hash>.<ext>` first
because both players' `/sub=` and `--sub-file=` are most reliable with local
paths. The URL hash means repeat clicks reuse the cached file.

PotPlayer **loads** the external subtitle into the track list but does not
override the user's "preferred subtitle language" preference, so embedded
tracks may still win the default selection. This is a PotPlayer limitation
(no CLI flag to force-select the external track) — users can either toggle
in the right-click menu or set "外挂字幕优先" once in F5 → 字幕 → 缺省语言.

---

## Known gaps

- **Code signing** — unsigned MSI will trigger SmartScreen.
- **No auto-update** — pull a fresh MSI from Releases manually for now.
- **Windows only** — macOS / Linux ports follow once the Win build
  stabilizes.

