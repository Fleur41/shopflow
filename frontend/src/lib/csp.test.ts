import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy, generateNonce } from "./csp";

function directive(policy: string, name: string): string {
  return policy.split("; ").find((part) => part.startsWith(`${name} `)) ?? "";
}

describe("buildContentSecurityPolicy", () => {
  const production = buildContentSecurityPolicy("abc123", false);

  it("only runs scripts that carry this request's nonce", () => {
    const scripts = directive(production, "script-src");
    expect(scripts).toContain("'nonce-abc123'");
    expect(scripts).toContain("'strict-dynamic'");
    expect(scripts).not.toContain("unsafe-inline");
    expect(scripts).not.toContain("unsafe-eval");
  });

  it("blocks framing, plugins and foreign form targets", () => {
    expect(directive(production, "frame-ancestors")).toBe("frame-ancestors 'none'");
    expect(directive(production, "object-src")).toBe("object-src 'none'");
    expect(directive(production, "form-action")).toBe("form-action 'self'");
    expect(directive(production, "connect-src")).toBe("connect-src 'self'");
    expect(production).toContain("upgrade-insecure-requests");
  });

  it("relaxes only what local development needs", () => {
    const development = buildContentSecurityPolicy("abc123", true);
    expect(directive(development, "script-src")).toContain("'unsafe-eval'");
    expect(development).not.toContain("upgrade-insecure-requests");
  });
});

describe("generateNonce", () => {
  it("is unpredictable and long enough", () => {
    const nonces = new Set(Array.from({ length: 100 }, generateNonce));
    expect(nonces.size).toBe(100);
    expect(atob([...nonces][0]!).length).toBe(16);
  });
});
