# PC frontend recovery evidence

Source session: `b1a4dd9d-b98c-406f-879d-cc5c9eabc9db`, recorded under the local Claude project history. Exact successful Edit/Write calls are preserved in `historical-successful-edits.json`; unsuccessful tool results were excluded.

## Fidelity

- `platform/nativePlayer.ts` and `platform/pc.ts`: complete original file snapshots plus the final successful historical Edit. The source line and timestamp are in `evidence.json`.
- `api/playbackTicket.ts` and `hooks/useThemeSettings.ts`: complete successful historical Write contents (session lines 15695 and 17437).
- `App.tsx` and `api/user.ts`: integrated snapshots of the current repository after applying evidenced functionality. Historical `originalFile` was null for these files, so these are **not byte-for-byte originals**. Exact historical edits remain available separately. Current storage reauthorization and other pre-existing work were retained.

The installed `1.21.1-pc.7` bundle `recovery/installed-pc-20260930/extracted/assets/index-Bdh2Yexe.js` independently contains `playbackTicket`, `/v1/auth/playback-ticket`, `last_watched`, `cyber_theme`, `/v1/user/preferences`, `subtitle_error`, and the release string. Run `node recovery/pc-source-candidate/frontend/inspect-history.mjs installed-evidence` to inspect offsets and bounded snippets.

## Changes intentionally not copied verbatim

- The hosted-beta PC default backend and automatic deletion of every saved loopback URL were not imported. The self-hosted build retains its neutral localhost default and user-editable backend setting.
- Playback credentials remain memory-only, isolated by backend and auth generation; failed/stale auth cannot launch a protected native stream. Credentials are attached only to the selected backend API, not third-party CDN URLs.
- Subtitle URL resolution now retains `/api` for backend-relative paths. Native streams, quality variants, attached subtitles, and native subtitle/history requests receive the same ticket.
- External-player native and fallback URL-scheme paths both retain ticketed URLs. Subtitle failures are reported instead of claiming subtitles loaded.
- History uses the backend's `last_watched`, bypasses HTTP cache, preserves special season zero, and sorts undated records consistently last. Favorites now carry the session cookie.
- The theme selection is persisted locally and tolerates malformed/unavailable storage.

## Backend contract gap

Read-only HTTPS check on 2026-09-30: `GET https://pioneer.fan:884/api/v1/user/preferences` returned **404**. The historical cloud-preference implementation is preserved in this candidate directory but is not activated in the application. Per-user homepage configuration likewise requires a backend contract and was not blindly mixed into this self-hosted frontend.

## Verification

- `npm run lint`: passed.
- `npm run build`: passed; existing chunk-size and mixed static/dynamic-import warnings remain.
- `node --test tests/pc-playback.test.mjs` from `frontend/`: focused regression coverage for ticket authentication, concurrent expiry/invalidation/backend changes, URL credential scope, native option forwarding, history chronology and backend URL settings.
- Live PC/WebView/native-window visual verification is coordinated by the root agent; this document does not claim that build/typechecks alone verify player UI.

The recovered source is local development work, not a newly published release or a GitHub sync.
