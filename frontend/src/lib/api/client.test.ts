import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authFetch } from "./client";

const ORIGIN = window.location.origin;
const problem = (status: number, code: string) =>
  new Response(JSON.stringify({ status, code, detail: code }), { status, headers: { "Content-Type": "application/problem+json" } });

type Call = { url: string; method: string; csrf: string | null; body: string };
let calls: Call[];
let responder: (call: Call) => Response;

beforeEach(() => {
  calls = [];
  document.cookie = "csrftoken=token-123";
  vi.stubGlobal("fetch", async (input: Request | string, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(input, ORIGIN), init);
    const call = {
      url: new URL(request.url).pathname,
      method: request.method,
      csrf: request.headers.get("X-CSRFToken"),
      body: await request.text(),
    };
    calls.push(call);
    await new Promise((resolve) => setTimeout(resolve, 5));
    return responder(call);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const post = (body: object) =>
  new Request(`${ORIGIN}/api/v1/stores/`, { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });

describe("authFetch", () => {
  it("adds the CSRF token to unsafe requests only", async () => {
    responder = () => new Response("{}", { status: 200 });

    await authFetch(new Request(`${ORIGIN}/api/v1/stores/`));
    await authFetch(post({ code: "A1" }));

    expect(calls.map((c) => [c.method, c.csrf])).toEqual([
      ["GET", null],
      ["POST", "token-123"],
    ]);
  });

  it("refreshes an expired session once and replays the original request", async () => {
    let expired = true;
    responder = (call) => {
      if (call.url === "/api/v1/auth/refresh/") {
        expired = false;
        return new Response("{}", { status: 200 });
      }
      return expired ? problem(401, "TOKEN_EXPIRED") : new Response('{"ok":true}', { status: 201 });
    };

    const response = await authFetch(post({ code: "A1" }));

    expect(response.status).toBe(201);
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/stores/", "/api/v1/auth/refresh/", "/api/v1/stores/"]);
    expect(calls[2]!.body).toBe('{"code":"A1"}');
    expect(calls[2]!.csrf).toBe("token-123");
  });

  it("shares one refresh between concurrent requests", async () => {
    let expired = true;
    responder = (call) => {
      if (call.url === "/api/v1/auth/refresh/") {
        expired = false;
        return new Response("{}", { status: 200 });
      }
      return expired ? problem(401, "TOKEN_EXPIRED") : new Response("{}", { status: 200 });
    };

    const results = await Promise.all([1, 2, 3].map(() => authFetch(new Request(`${ORIGIN}/api/v1/stores/`))));

    expect(results.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(calls.filter((c) => c.url === "/api/v1/auth/refresh/")).toHaveLength(1);
  });

  it("gives up when the refresh fails, returning the original 401", async () => {
    responder = (call) =>
      call.url === "/api/v1/auth/refresh/" ? problem(401, "SESSION_EXPIRED") : problem(401, "TOKEN_EXPIRED");

    const response = await authFetch(new Request(`${ORIGIN}/api/v1/stores/`));

    expect(response.status).toBe(401);
    expect(calls).toHaveLength(2);
  });

  it("does not refresh for other 401s (e.g. a revoked session)", async () => {
    responder = () => problem(401, "SESSION_REVOKED");

    await authFetch(new Request(`${ORIGIN}/api/v1/stores/`));

    expect(calls).toHaveLength(1);
  });
});
