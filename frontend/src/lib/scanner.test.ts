import { describe, expect, it } from "vitest";

import { createWedgeDetector } from "./scanner";

function feed(keys: string[], gap: number) {
  const detector = createWedgeDetector();
  let at = 1000;
  let result: string | null = null;
  for (const key of keys) {
    result = detector.key(key, at);
    at += gap;
  }
  return result;
}

describe("keyboard-wedge scanner detection", () => {
  it("treats a fast burst ending in Enter as a scan", () => {
    expect(feed([..."6161000000017", "Enter"], 8)).toBe("6161000000017");
  });

  it("ignores people typing", () => {
    expect(feed([..."6161", "Enter"], 180)).toBeNull();
  });

  it("ignores short bursts and Enter on its own", () => {
    expect(feed(["1", "2", "Enter"], 5)).toBeNull();
    expect(feed(["Enter"], 5)).toBeNull();
  });

  it("starts over after a pause", () => {
    const detector = createWedgeDetector();
    for (const [i, key] of [..."99"].entries()) detector.key(key, i * 5);
    let at = 1000; // a pause, then a real scan
    let code: string | null = null;
    for (const key of [..."ABC123", "Enter"]) code = detector.key(key, (at += 5));
    expect(code).toBe("ABC123");
  });
});
