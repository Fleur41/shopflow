"use client";

import { useEffect, useRef } from "react";

/**
 * USB and Bluetooth barcode scanners act as keyboards ("keyboard wedge"): they
 * type the code very fast and press Enter. People don't type that fast, so a
 * burst of at least MIN_LENGTH characters, each within MAX_GAP_MS of the last,
 * ending in Enter, is a scan.
 */
export const MAX_GAP_MS = 60;
export const MIN_LENGTH = 4;

export type WedgeDetector = {
  /** Feed a key; returns the scanned code when the key completes a scan. */
  key(key: string, at: number): string | null;
};

export function createWedgeDetector(): WedgeDetector {
  let buffer = "";
  let last = -Infinity;
  return {
    key(key, at) {
      if (at - last > MAX_GAP_MS) buffer = "";
      last = at;
      if (key === "Enter") {
        const code = buffer;
        buffer = "";
        return code.length >= MIN_LENGTH ? code : null;
      }
      if (key.length === 1) buffer += key;
      else buffer = ""; // Shift, arrows etc. break a burst
      return null;
    },
  };
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * Catch scans while focus is anywhere but a text field (after tapping a cart
 * button, say), so the cashier never has to click back into the scan box.
 */
export function useScannerWedge(onScan: (code: string) => void, enabled: boolean): void {
  const handler = useRef(onScan);
  useEffect(() => {
    handler.current = onScan;
  }, [onScan]);

  useEffect(() => {
    if (!enabled) return;
    const detector = createWedgeDetector();
    function onKeyDown(event: KeyboardEvent) {
      if (isEditable(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
      const code = detector.key(event.key, event.timeStamp);
      if (event.key === "Enter" && code) {
        event.preventDefault(); // don't also "click" the focused button
        handler.current(code);
      }
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [enabled]);
}
