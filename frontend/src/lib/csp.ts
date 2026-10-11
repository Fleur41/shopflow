/**
 * Content-Security-Policy for every page (docs/SECURITY.md §5).
 *
 * Scripts and styles run only from our origin or with the per-request nonce,
 * so injected markup cannot execute. `strict-dynamic` lets nonce-trusted
 * scripts load the app's own chunks. Development additionally needs eval
 * (React debugging), inline styles (error overlay) and the HMR websocket.
 *
 * Product images come from a separate media origin (object storage or a CDN;
 * Django's own port locally), which `img-src` alone allows (SECURITY.md §7).
 */
export function buildContentSecurityPolicy(nonce: string, isDev: boolean, mediaOrigin?: string): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(isDev ? ["'unsafe-eval'"] : [])],
    "style-src": isDev ? ["'self'", "'unsafe-inline'"] : ["'self'", `'nonce-${nonce}'`],
    "img-src": ["'self'", "blob:", "data:", ...originOf(mediaOrigin)],
    "font-src": ["'self'"],
    "connect-src": ["'self'", ...(isDev ? ["ws:"] : [])],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  const policy = Object.entries(directives).map(([name, values]) => `${name} ${values.join(" ")}`);
  if (!isDev) policy.push("upgrade-insecure-requests");
  return policy.join("; ");
}

/** Just the origin, so a misconfigured value can't add other directives. */
function originOf(value: string | undefined): string[] {
  if (!value) return [];
  try {
    const { origin } = new URL(value);
    return origin === "null" ? [] : [origin];
  } catch {
    return [];
  }
}

export function generateNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}
