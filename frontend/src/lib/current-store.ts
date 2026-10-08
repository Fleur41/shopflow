"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { Me, StoreSummary } from "./api/types";

const CHANGE_EVENT = "shopflow:store-change";

function read(key: string | null): string | null {
  if (!key) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // storage unavailable (e.g. private mode): fall back to the first store
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange); // other tabs
  window.addEventListener(CHANGE_EVENT, onChange); // this tab
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/**
 * The store the user is working in. Remembered per business in this browser
 * as a convenience only: the server checks store access on every request.
 */
export function useCurrentStore(me: Me | undefined): [StoreSummary | null, (id: string) => void] {
  const organizationId = me?.organization?.id;
  const storageKey = organizationId ? `shopflow:store:${organizationId}` : null;
  const selectedId = useSyncExternalStore(
    subscribe,
    () => read(storageKey),
    () => null,
  );

  const select = useCallback(
    (id: string) => {
      if (!storageKey) return;
      try {
        window.localStorage.setItem(storageKey, id);
      } catch {
        // Not persisted in this browser; nothing else to do.
      }
      window.dispatchEvent(new Event(CHANGE_EVENT));
    },
    [storageKey],
  );

  const stores = me?.access?.stores ?? [];
  const current = stores.find((store) => store.id === selectedId) ?? stores[0] ?? null;
  return [current, select];
}
