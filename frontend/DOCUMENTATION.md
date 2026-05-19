# CyberStream - Developer & Architecture Documentation

This document serves as a comprehensive technical guide to the **CyberStream** codebase, designed to help developers, designers, and maintainers understand the structural logic, data flow, and design system of the application.

---

## 1. Architecture Overview

CyberStream is a Single Page Application (SPA) built with React and Vite. It serves as a dedicated frontend to a custom media server backend capable of streaming video, tracking watch history, matching TMDB databases, and extracting tech-metadata directly from MKV/MP4 files.

### 1.1 Data Flow & Services

The application communicates with the backend exclusively through `/src/api`.
This service layer intercepts raw `openapi.json` configurations and transforms them into UI-friendly objects based on `/src/types/index.ts`.

*   **API Mapping strategy:** Raw API objects (e.g., `ApiMovieDetailed`) act as Data Transfer Objects (DTOs). Functions like `mapApiMovieToUi` serve as Serializers. This prevents backend schema changes from shattering the React views.
*   **Authentication:** Managed via device-specific UUIDs (`crypto.randomUUID()`) injected into API calls or using lightweight JWT/sessions (depending on the API env).
*   **Media Streaming:** Uses standard HTTP Live Streaming or direct MKV/MP4 HTTP byte-range requests depending on the backend delivery configuration.

---

## 2. Design System & Theming

The visual identity of CyberStream is strictly enforced. It aims for a "functional HUD" look, rejecting the warm gradients of consumer apps in favor of analytical, dashboard-like precision.

### 2.1 Color Palette
*   **Primary Accent (`text-primary`, `bg-primary`):** Neon Cyan (`#00f3ff`). Used sparingly to draw eye focus (play buttons, progress bars, active states).
*   **Secondary/Highlight:** Purples/Magentas (`#c722ee`). Used to denote premium technical flags (like Dolby Atmos).
*   **Backgrounds:** Deep blacks (`#000000`, `bg-black/90`) transitioning into dark greys (`#111111`) to simulate screen depth.
*   **Borders:** Semi-transparent white (`border-white/10` or `border-white/20`) to create glassmorphism panels.

### 2.2 Typography
*   **Orbitron:** Used for primary application headers, hero titles, and stylized numeric readings.
*   **Rajdhani:** Used for technical data readouts (timestamps, file sizes) due to its squared, industrial feel.
*   **Inter (fallback):** Standard sans-serif for long-form overviews to preserve legibility.

### 2.3 Motion Design (Framer Motion)
*   Routes use `<AnimatePresence mode="wait">` to crossfade smoothly.
*   Hover states scale slightly (`scale-[1.02]`) while increasing opacity and injecting heavy CSS `drop-shadow`.

---

## 3. Core Components

### 3.1 Player (`/src/components/Player.tsx`)
The centerpiece of the application.
*   **State Machine:** Reactively captures `isPlaying`, `isDraggingSeek`, `isBuffering`.
*   **Resource Switching:** Handles the complex logic of switching between multi-source assets (e.g., switching from a 1080p source to a 4K REMUX source) without completely mounting a new view.
*   **Audio Transcode:** Integrates experimental features for syncing separate audio channels via `audioRef` and `videoRef` concurrent playback.

### 3.2 MovieDetail (`/src/features/MovieDetail.tsx`)
*   **Layer 1 (Hero Background):** Deeply blurred poster/backdrop utilizing `backdrop-filter`.
*   **Layer 2 (Content Box):** The main descriptor, holding metadata maps.
*   **TechSpecs:** Iterates across the `movie.tech_specs` object rendering dedicated `.tsx` badges utilizing standard SVGs from Lucide-React.
*   **Discovery Carousel:** Implements a horizontal `onWheel` snap-scroll container at the bottom (`#recommendations`) utilizing `overflow-x-auto` & CSS scroll snapping, bypassing heavy JS sliders.

---

## 4. Workflows & States

### 4.1 "Continue Watching" & History tracking
The player emits heartbeat `reportHistory()` events every 10 seconds via `setInterval`. When a user navigates to the Home page, the `history` slice reads these timestamps and calculates the percentage to resume an asset via `progress / duration`.

### 4.2 Metadata Workbench
Admins can navigate to settings or detail pages to "Re-scrape" a title. This triggers a `POST /metadata/match` to TMDB. Forms handle fields blocking via `metadata_locked_fields` array to prevent accidental overwrites of hand-tuned data.

---

## 5. Development Guidelines

*   **No Magic Numbers in CSS:** If something is glowing, use Tailwind variants (`shadow-[0_0_10px_rgba(...)]`). 
*   **Types Over Inference:** Any parameter injected into a UI card must adhere to the `Movie` interface in `src/types/index.ts`.
*   **Fallbacks:** Given scraping is unpredictable, UI elements must degrade gracefully when an asset is missing an Overview, Backdrop, or Tech Spec flag. Avoid `null` exceptions by heavily utilizing `?.` optional chaining.
