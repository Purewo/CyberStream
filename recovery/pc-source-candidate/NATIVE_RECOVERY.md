# Native player recovery evidence

The `pc/src-tauri/src/native_player/` files in this candidate are historical
reconstruction artifacts. The live `pc/src-tauri/src/native_player/` tree additionally
contains the corrective changes listed below. Do not overwrite the live tree with
the candidate to retain those fixes.

## Reconstruction

- Baseline: Git commit `d853118d2d98299161fae284dd88026fb6406a65`, 2026-05-31.
- Source: the local Claude project history, principally session
  `b1a4dd9d-b98c-406f-879d-cc5c9eabc9db`, and its subagent histories.
- Only successful `Edit`/`Write` results for the historical
  `CyberStream-frontend-hosted-beta/pc/src-tauri/src/native_player/` path were used.
- 57 native edits replayed exactly; every old string matched its source.
- 72 intermediate native `Read` excerpts matched the reconstructed state exactly;
  no native excerpt mismatch or edit gap remains in these available records.
- The final native modification in these records is 2026-06-24 17:47:51 UTC.
- `ffi.rs`, `render.rs`, and `window.rs` have no later hosted edits in these records;
  the candidate retains their Git baseline versions.
- `native-source-provenance.json` records source session, line, tool-use ID, date,
  and SHA-256. It does not contain a copy of the conversations or credentials.
- The June 12 self-hosted changes form a different development line. They were
  reverted in the June 13 history and must not be replayed into the hosted line.

Reproduce candidates with `node recovery/recover-native-history.cjs --recover`.
This writes only under `recovery/pc-source-candidate`, never into the live source.
The companion `--emit-native-patch` outputs a proposed patch for explicit review.
Candidate shell files are outside this native recovery's verification scope.

## Restored behavior

Settings gear with speed, sleep timer, A-B loop, subtitle/audio timing, subtitle
font size/position/color, ASS style override, brightness/contrast/saturation/gamma,
aspect ratio, and screenshot. Independent bounded popup cards for settings,
subtitles, and audio; richer subtitle metadata; playback ticket support for native
subtitle requests and history heartbeat; visible playback-load errors.

## Corrective changes in the live tree

- Preserve `/api/` when resolving bound subtitle paths; attach the playback ticket
  only for same-origin subtitle streams.
- Redact request/media URLs from logs and HTTP error strings.
- Queue work through `mpv_command_async`, removing a detached thread that retained
  an unowned mpv pointer after the player window could close.
- Stop/join heartbeat on drop, including early player initialization errors.
- Include resource identity in asynchronous subtitle results. Old results cannot
  select, bind, or remove tracks from a newly selected episode.
- Reset A-B state and old subtitle search state on episode switches.
- Generate unique preview filenames to avoid simultaneous downloads overwriting.
- Observe actual mpv settings (including initial subtitle font size) instead of
  showing optimistic UI values; rejected setters show errors. Normalize mpv's
  returned color/aspect formats for selected-state rendering.
- Keep subtitles inside the video viewport with `sub-use-margins=no`, and keep
  popup scrolling at a stable height instead of shrinking at the bottom.
- Opt-in debug-only `CYBER_MPV_TEST_PIPE=<suffix>` exposes a local named pipe
  `\\.\pipe\cyberstream-recovery-<suffix>` for native property verification. The
  suffix is limited to 1–48 ASCII letters, digits, or hyphens. Release builds do
  not include this instrumentation.

## Verification

`cargo test --lib --no-default-features` in `pc/src-tauri`: 10 tests passed
(7 native, 3 external-player).
One test exercises the actual installed libmpv for video controls, synchronization,
subtitle styling, speed, and ASS override. Additional tests cover same-origin
subtitle authentication, URL redaction, queued-command teardown, and debug pipe
validation. Real-mpv observer coverage verifies the initial font size, every
settings property update, rejected color changes, A-B clearing, and aspect reset.
`git diff --check -- pc/src-tauri/src/native_player` passes.

Real GUI verification is performed separately by the coordinating agent; unit
tests do not by themselves certify all popup interactions or backend integration.
