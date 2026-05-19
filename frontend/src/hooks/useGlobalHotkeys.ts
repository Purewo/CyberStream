// Global, app-wide keyboard shortcuts.
//
// Only ones that should fire from anywhere in the app live here. Component-
// scoped hotkeys (Player seek, dialog confirm) keep their own listeners.
// Editing fields (input/textarea/contenteditable) suppress everything so we
// never eat user typing.

import { useEffect } from 'react';
import { toggleFullscreen } from '../platform';

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
    };
    window.addEventListener('keydown', onKey, { capture: true });
    return () => window.removeEventListener('keydown', onKey, { capture: true });
  }, []);
}
