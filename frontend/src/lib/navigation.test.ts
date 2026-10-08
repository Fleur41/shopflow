import { describe, expect, it } from "vitest";

import { safeNextPath } from "./navigation";

describe("safeNextPath", () => {
  it.each(["/", "/settings/stores", "/settings/staff?x=1"])("keeps same-site path %s", (path) => {
    expect(safeNextPath(path)).toBe(path);
  });

  it.each([null, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"])(
    "rejects %s (open redirect)",
    (value) => {
      expect(safeNextPath(value)).toBe("/");
    },
  );
});
