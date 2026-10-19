# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- `npm run dev` 鈥?Vite dev server on port 3000 (host `0.0.0.0`).
- `npm run build` 鈥?Type-check (`tsc`) then Vite production build.
- `npm run lint` 鈥?Type-check only (`tsc --noEmit`). There is no ESLint/Prettier; type errors are the lint signal.
- `npm run preview` 鈥?Serve the built `dist/`.
- `node fetch_openapi.mjs` refreshes `openapi.json` from `https://pioneer.fan:884/api/v1/openapi.json`, using the same backend as the Web frontend.

There is no test runner configured. If you add tests, set up the framework yourself.

Path alias `@` 鈫?`./src` is configured in `vite.config.ts`, but most existing code uses relative imports.

## Backend & runtime config

- The app is a pure SPA frontend; the backend is configured by `API_BASE` in `src/constants/index.ts` (currently `https://pioneer.fan:884/api`, confirmed by the user on 2026-09-30). Changing backend = edit that constant and `fetch_openapi.mjs` together. Backend deployment is owned by the server-side Codex.
- The `openapi-1.21.0-beta/` directory and `openapi.json` are reference specs for the backend contract. Treat them as documentation; the typed UI layer lives in `src/api/` and `src/types/index.ts`.
- A device UUID is generated client-side via `getDeviceId()` (`src/api/core.ts`) and persisted in `localStorage['cyber_device_id']` for auth.

## Architecture

### Layered data flow

```
Backend (OpenAPI)  鈫? src/api/*  鈫? src/types  鈫? src/features + src/components
                      (DTOs +         (UI shape)    (views/UI)
                       serializers)
```

- **`src/api/core.ts`** is the seam. `fetchApi<T>()` wraps `fetch` against `API_BASE`, normalizes the `{ code, msg, data }` envelope, and surfaces network failures via the global toast. `mapApiMovieToUi()` is the canonical adapter that converts raw `ApiMovieSimple`/`ApiMovieDetailed` DTOs into the UI `Movie` type 鈥?backend schema drift should be absorbed here, not in views. `resolveAssetUrl()` rewrites `/api/...` and `/v1/...` paths against `API_BASE`.
- Per-domain services live next to `core.ts`: `home.ts`, `library.ts`, `movie.ts`, `resource.ts`, `user.ts`, `storage.ts`, `system.ts`, plus a `schema.ts`. `src/api/index.ts` re-exports them all; consumers import from `../api`.
- **`src/types/index.ts`** is the single source of truth for UI-side interfaces (`Movie`, `Resource`, `TechSpecs`, `PlaybackUserData`, `ResourceSubtitleItem`, etc.). Anything entering a view should be typed against these, not the raw `Api*` shapes.

### App shell & routing

- `src/App.tsx` is the root. There is **no react-router**: navigation is hand-rolled state in `src/hooks/useAppRouting.ts`. Two state axes:
  - `currentView` 鈥?top-level page (`'home' | 'library' | 'libraries' | 'add_library' | 'leaderboard' | 'history' | 'profile' | 'search' | 'review'`).
  - `overlayView` 鈥?full-screen overlay on top of the current view (`'none' | 'detail' | 'player'`). The Player hides the navbar/footer; MovieDetail does not.
- Scroll position is preserved manually: `useAppRouting` snapshots `scrollContainerRef.current.scrollTop` into `savedScroll` when opening an overlay and restores it on close.
- Modals (`ContextMenu`, `MetadataEditor`, `TMDBMatchModal`, `AddToLibraryModal`, `ScanProgressBar`, `Toaster`) are rendered globally from `App.tsx`, not per-view.

### Cross-component communication

The app uses the `window` event bus for one-to-many signals that would otherwise require prop-drilling:

- `show-movie-context-menu` 鈥?any movie card dispatches this with `{ x, y, movie }`; `App.tsx` listens and opens the global `ContextMenu`.
- `library-list-dirty` 鈥?fired after a library mutation to trigger refreshes.
- `movie-updated` 鈥?fired with the updated `Movie` after a TMDB match/edit.

When you add features that need to invalidate shared state across screens, prefer extending these events over threading callbacks through deep prop chains.

### Hooks split

`App.tsx` is thin because three hooks own most state:

- `useAppRouting` 鈥?view/overlay state, modal state, scroll preservation, and the `navigateTo` / `openMovie` / `openPlayer` / `closeOverlay` actions.
- `useUserData` 鈥?favorites, history, notifications, libraries; loaded once on mount and refreshed via the returned helpers (`refreshHistory`, `refreshLibraries`, `handleToggleFavorite`, etc.).
- `useThemeSettings` 鈥?settings + theme name; `currentTheme` is fed into a `<style>{getStyles(...)}</style>` block at the root.

### Player & resources

`src/components/Player.tsx` is the centerpiece and handles multi-source switching (e.g., 1080p 鈫?4K REMUX) without unmounting, audio-track sync via parallel `audioRef`/`videoRef`, and history heartbeats (every 10s the player reports progress via `userService.reportHistory`). The `PlayOptions` carried through `useAppRouting.openPlayer` selects the initial resource/season/episode.

A movie can have multiple `Resource` entries, each with `tech_specs` (`resolution`, `codec`, `flag_is_4k`, `flag_is_remux`, `flag_is_dolby_vision`, `audio_is_atmos`, etc.). `mapApiMovieToUi` flattens the **first** resource's tech specs onto the `Movie` for badge rendering 鈥?be aware when adding fields that touch tech badges.

## Conventions

- **Language:** UI strings, toasts, alerts, and many comments are Chinese (Simplified). Match existing tone when adding user-facing copy. Code identifiers stay English.
- **Styling:** Tailwind utility classes inline. Theme-driven colors come from CSS variables injected by `getStyles()` (driven by `THEMES` in `src/constants/index.ts`: `CYBER`, `ARASAKA`, `GOLDEN`). Don't introduce a CSS-in-JS lib or a separate stylesheet for component styling.
- **Optional chaining everywhere on movie data.** Scraped metadata is unreliable 鈥?`poster_url`, `backdrop_url`, `tech_specs.*`, `user_data.*` all may be missing. Existing code degrades gracefully; new code should too.
- **No `window.confirm` / `window.alert` for destructive actions** 鈥?the app may run inside an iframe where they are blocked. Use the `toast` helper from `src/utils` and inline confirmations.
- **Asset URLs:** always pipe backend-relative URLs through `resolveAssetUrl()` (or rely on `mapApiMovieToUi` having done it). Do not concatenate `API_BASE` manually.
- **Adding an API call:** put the fetch in the appropriate `src/api/<domain>.ts`, return UI-typed objects (use `mapApiMovieToUi` if the response includes movies), and re-export from `src/api/index.ts` if it is a new service.

## Reference docs in repo

- `README.md` 鈥?feature overview and design system summary.
- `DOCUMENTATION.md` 鈥?deeper architecture/design narrative (data flow, theming, Player internals, workflows). Read this when touching the design system or Player.
- `瀛楀箷鎺ュ彛璁捐寤鸿.md` 鈥?subtitle interface design notes (Chinese).
- `migrated_prompt_history/` 鈥?historical prompts; not load-bearing for current code.

