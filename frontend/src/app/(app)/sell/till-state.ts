"use client";

import { useCallback, useEffect, useState } from "react";

import type { CartLine } from "@/lib/cart";

export type TillCustomer = {
  id: string;
  name: string;
  balance: string | null;
  availableCredit: string | null;
};

export type TillState = {
  /** One per sale attempt: a retried sale with the same id is recorded once. */
  txnId: string;
  lines: CartLine[];
  customer: TillCustomer | null;
};

function fresh(): TillState {
  return { txnId: crypto.randomUUID(), lines: [], customer: null };
}

function load(key: string | null): TillState {
  if (!key) return fresh();
  try {
    const saved = window.localStorage.getItem(key);
    if (saved) {
      const parsed = JSON.parse(saved) as TillState;
      if (typeof parsed.txnId === "string" && Array.isArray(parsed.lines)) return parsed;
    }
  } catch {
    // Unreadable or unavailable: start an empty cart.
  }
  return fresh();
}

/**
 * The cart for one store, kept in this browser so a reload or a dropped
 * connection doesn't lose a half-scanned sale. A convenience only: nothing
 * is sold until the server confirms it.
 */
export function useTillState(storageKey: string | null) {
  const [state, setState] = useState<TillState>(() => (typeof window === "undefined" ? fresh() : load(storageKey)));
  const [loadedKey, setLoadedKey] = useState(storageKey);

  // A different store or business: load its cart. (Adjusting state while
  // rendering, as React recommends, rather than in an effect.)
  if (loadedKey !== storageKey) {
    setLoadedKey(storageKey);
    setState(load(storageKey));
  }

  useEffect(() => {
    if (!storageKey) return;
    try {
      if (state.lines.length === 0 && !state.customer) window.localStorage.removeItem(storageKey);
      else window.localStorage.setItem(storageKey, JSON.stringify(state));
    } catch {
      // Not saved in this browser; the sale still works.
    }
  }, [state, storageKey]);

  const update = useCallback((change: (state: TillState) => TillState) => setState(change), []);
  const clear = useCallback(() => setState(fresh()), []);
  return { state, update, clear };
}
