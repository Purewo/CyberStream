# CyberStream PC 1.21.1

Native player + external handoff with subtitle preload.

## Download

- `CyberStream_1.21.1_x64_en-US.msi` — Windows 11 x64

The installer bundles libmpv, so you don't need to install mpv separately.
Backend (Flask) still runs on your NAS or home server — this client only
replaces the browser/frontend half.

> **SmartScreen warning:** The MSI is unsigned. Click *More info → Run anyway*.
> Code signing is on the post-1.21 list.

## Highlights

### Native player window

The big addition since `1.21.0-pc.0`. When you click 播放 on a movie detail
page, CyberStream now spawns its own Win32 window driven by libmpv + egui_glow
instead of falling back to the browser `<video>` element. That means:

- Real 4K HEVC / Dolby Vision Profile 5 playback without browser decoder
  caps
- TrueHD / Atmos pass-through
- Per-season ComboBox picker (handles 14-season shows cleanly)
- 9-control bottom bar: previous/next episode, play/pause, volume, subtitle
  picker, audio track picker, speed, fullscreen, quit, plus a full-width
  progress bar
- Right-side detail panel in windowed mode (resources / seasons /
  bound subtitles); fully hidden in fullscreen so it never blocks the
  picture
- In-window online subtitle search + bind + preview, with a 3-section
  picker (bound / embedded / temporary preview) and current-track
  highlighting
- Auto-pick default subtitle on launch (bound > embedded)
- Rust-side history heartbeat: POSTs to `/api/v1/user/history` every 10s
  with the same `device_id` the webview uses, so progress syncs even
  while the browser tab is hidden

### External player handoff (PotPlayer / VLC) — now with subtitles

Previously the PotPlayer / VLC buttons on the detail page just opened a
URL scheme (`potplayer://...`, `vlc://...`). That works for the video URL
but can't pass a subtitle parameter. As of 1.21.1 the PC client locates
`PotPlayerMini64.exe` / `vlc.exe` via the Windows registry + Program Files
and spawns them directly with proper CLI args:

- **PotPlayer**: `/current <stream_url> /sub=<local_path>`. Subtitle is
  pre-downloaded to `%TEMP%\cyberstream_sub_<hash>.<ext>` so the
  player's `/sub=` parser sees a local file (HTTP URLs hang or get
  truncated). `/current` reuses an existing window — without it,
  PotPlayer would spawn a second process and both would fight over the
  GL/audio device.
- **VLC**: `<stream_url> :sub-file=<local_path>`. Uses MRL options
  (colon-prefixed) instead of the global `--sub-file=` flag, which has
  a 3.x bug where HTTP subtitle URLs get treated as a second video
  input.

If the `.exe` isn't found we fall back to the old URL-scheme path so
nothing regresses.

> **Note**: PotPlayer **loads** the external subtitle to the track list,
> but doesn't override the user's "preferred subtitle language"
> preference, so on videos with embedded tracks PotPlayer may still pick
> the embedded one as the default display. Right-click → 字幕 → choose
> the external entry, or set "外挂字幕优先" once in F5 → 字幕 → 缺省语言.
> This is a PotPlayer CLI limitation (no flag to force-select). VLC
> selects the external subtitle correctly.

### UI polish

- Bottom bar redesigned: removed redundant ChevronDown indicators on the
  three popup buttons (subtitle / audio / speed), trailing-zero stripped
  from speed labels (`1.00x` → `1x`, `1.5x` stays), fullscreen icon
  switched to the bracket-square style instead of the diagonal-arrow.
- Play button restyled with proper drop shadow + arc highlight for
  depth, plus visible press feedback (button sinks 1px and darkens
  18% on click).
- Toast notifications redesigned: cyan/magenta/neon-yellow color
  scheme on glass-blurred black, with corner cuts, type tags
  (`ACK / ERR / WARN / INFO`), and a countdown progress bar — replaces
  the previous default-Tailwind green/red look.

### TV series detail page is now snappy

`getResources(id, season?)` picks up the new `season` query parameter
that the backend added in 1.21. The detail page only hydrates one
season on entry instead of all 14, so a 7-season show now opens in
~300ms / 360KB instead of 1.86s / 1.18MB. Other seasons lazy-load if
the user navigates to them. Cross-season "继续播放" leakage and
"从头播放" mistakenly resuming have both been fixed at the same time.

## Verifying after install

1. Open CyberStream.
2. Confirm Profile → SYSTEM → 后端服务器 shows the right backend URL,
   change if needed.
3. Open any movie, click *播放*. The native player window should
   open with the libmpv backend (no browser `<video>` fallback).
4. Click any external-player icon (PotPlayer / VLC) on a movie that has
   a default-bound subtitle. The player should launch with the subtitle
   pre-loaded (look for the language tag in PotPlayer's subtitle menu /
   VLC's auto-selected track).

## Known limitations

- Unsigned installer, no auto-updater.
- macOS / Linux: not yet.
- PotPlayer external subtitle is loaded but not auto-selected when the
  video has embedded tracks (see note above). VLC works correctly.

## Source

- Tag: `v1.21.1`
- Build instructions: [pc/README.md](README.md)
- Earlier release notes: [RELEASE_NOTES_TEMPLATE.md](RELEASE_NOTES_TEMPLATE.md) (1.21.0-pc.0)
