// Global, app-wide keyboard shortcuts.
//
// Only ones that should fire from anywhere in the app live here. Component-
// scoped hotkeys (Player seek, dialog confirm) keep their own listeners.
// Editing fields (input/textarea/contenteditable) suppress everything so we
// never eat user typing.

import { useEffect } from 'react';
import { isFullscreen, toggleFullscreen } from '../platform';

function isEditableTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return el.isContentEditable;
}

export function useGlobalHotkeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return;
      // F11 — toggle window fullscreen (Tauri) or document fullscreen (Web).
      if (e.key === 'F11') {
        e.preventDefault();
        toggleFullscreen().catch(() => { /* permission denied — ignore */ });
        return;
      }
      // Escape only exits fullscreen — never closes overlays here. Overlay
      // close is handled inside Player.tsx / modals so they can prompt for
      // unsaved state. We bail early when not fullscreen so the keystroke
      // bubbles to whatever component wanted it.
      if (e.key === 'Escape') {
        isFullscreen().then((fs) => {
          if (fs) {
            // Don't preventDefault — components downstream may still want
            // Esc, but make sure we leave fullscreen first.
            toggleFullscreen().catch(() => {});
          }
        }).catch(() => {});
        return;
      }
    };
    window.addEventListener('keydown', onKey, { capture: true });
    return () => window.removeEventListener('keydown', onKey, { capture: true });
  }, []);
}
