/**
 * Typed API client (types generated from the backend's OpenAPI schema).
 *
 * The browser talks to the API on the same origin with HttpOnly cookies
 * (docs/SECURITY.md §2). This module adds the CSRF header to unsafe requests
 * and, when the access token has expired, refreshes it once (shared by all
 * concurrent requests) and retries the original request.
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const REFRESH_PATH = "/api/v1/auth/refresh/";
const NO_RETRY_PATHS = [REFRESH_PATH, "/api/v1/auth/login/", "/api/v1/auth/signup/"];

let refreshInFlight: Promise<boolean> | null = null;

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

export async function getCsrfToken(): Promise<string> {
  const fromCookie = readCookie("csrftoken");
  if (fromCookie) return fromCookie;
  const response = await fetch("/api/v1/auth/csrf/", { credentials: "same-origin" });
  const body = (await response.json()) as { csrf_token: string };
  return body.csrf_token;
}

async function withCsrf(request: Request): Promise<Request> {
  if (!UNSAFE_METHODS.has(request.method)) return request;
  const headers = new Headers(request.headers);
  headers.set("X-CSRFToken", await getCsrfToken());
  return new Request(request, { headers });
}

/** Refresh the session once, however many requests are waiting for it. */
export function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(REFRESH_PATH, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": await getCsrfToken() },
      });
      return response.ok;
    } catch {
      return false;
    }
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function problemCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.clone().json()) as { code?: unknown };
    return typeof body.code === "string" ? body.code : null;
  } catch {
    return null;
  }
}

export async function authFetch(input: Request): Promise<Response> {
  const request = await withCsrf(input);
  const retry = request.clone();
  const response = await fetch(request);

  const path = new URL(request.url).pathname;
  if (
    response.status === 401 &&
    !NO_RETRY_PATHS.includes(path) &&
    (await problemCode(response)) === "TOKEN_EXPIRED" &&
    (await refreshSession())
  ) {
    return fetch(retry);
  }
  return response;
}

export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  credentials: "same-origin",
  fetch: authFetch,
});

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
