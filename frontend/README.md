<div align="center">
  <img src="https://i.imgur.com/KxTMBzS.png" alt="CyberStream" width="200" height="200" style="border-radius: 50%" />
  <h1>CyberStream</h1>
  <p><strong>A Next-Gen, Sci-Fi UI Media Streaming Platform & Metadata Manager</strong></p>
  <p>
    <a href="#features">Features</a> •
    <a href="#tech-stack">Tech Stack</a> •
    <a href="#getting-started">Getting Started</a> •
    <a href="DOCUMENTATION.md">Full Documentation</a>
  </p>
</div>

---

## 🌌 Introduction

**CyberStream** is to media what cyberpunk is to science fiction: an immersive, aggressively futuristic, and neon-drenched approach to organizing and consuming your media libraries.

Designed as an alternative client/frontend to traditional media servers (like Plex, Emby, Jellyfin), **CyberStream** offers a completely revitalized UI focused on typography, motion, dark mode aesthetics, and deep technical media insights. It doesn't just play your movies; it visualizes the technology delivering them (codecs, bitrates, resolutions).

## 🚀 Key Features

*   **Sci-Fi/Cyberpunk UI:** High-contrast tech screens, neon glow effects (`#00f3ff` & `#c722ee`), monospace typography (`Orbitron`, `Rajdhani`, `JetBrains Mono`), and seamless React-based motion transitions.
*   **Deep Tech Specs:** Automatically extracts and displays technical file data: Remux tags, HDR/Dolby Vision, Dolby Atmos flags, Bitrates, and Storage routing.
*   **Advanced Player Experience:** Integrated HTML5 Player customized with interactive Sci-Fi progress rings, multi-season/source switching, audio transcoding toggles, and metadata badging.
*   **Media Management & Scraping:** Built-in dashboard to re-scrape metadata from TMDB, match locked/unlocked fields, and configure automatic background parsing.
*   **Robust State Management:** Handles user watch history, continue watching logic, dynamic carousels, and infinite horizontal sliding grids out-of-the-box.

---

## 🛠 Tech Stack

*   **Framework:** React 18 + Vite using TypeScript.
*   **Styling:** Tailwind CSS + custom CSS variables.
*   **Icons:** Lucide-React.
*   **Animation:** Framer Motion (`motion/react`) for page transitions and micro-interactions.
*   **Backend Interface:** Strongly typed OpenAPI v1 client mapping (`src/api/index.ts`).

---

## 📦 Getting Started

### Prerequisites

Ensure you have Node.js (v18+) installed. This is a pure client-side SPA designed to connect to the CyberStream backend (configured via `API_BASE`).

### Installation

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Run the development server:**
   ```bash
   npm run dev
   ```

3. **Build for production:**
   ```bash
   npm run build
   ```

---

## 📚 Project Structure

*   **/src/components**: Reusable UI blocks.
    *   `/movies`: Card variants, Grids, and Carousels.
    *   `/ui`: Specialized Sci-Fi atoms (badges, neon buttons, loaders).
    *   `Player.tsx`: The core HTML5 video streaming player.
*   **/src/features**: Major application views/pages (e.g., `MovieDetail.tsx`, `Home.tsx`, `Library.tsx`).
*   **/src/api**: API interfaces and serializers bridging the raw REST OpenAPI to typed UI data models.
*   **/src/types/index.ts**: Single source of truth for TypeScript interfaces (Movie, Resource, TechSpecs).

*(See [DOCUMENTATION.md](DOCUMENTATION.md) for in-depth technical breakdowns and design philosophy.)*
