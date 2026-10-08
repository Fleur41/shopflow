import type { NextConfig } from "next";

// In development, Next.js forwards /api/* to Django so the browser sees a
// single origin (docs/ARCHITECTURE.md, ADR-04). In deployed environments the
// reverse proxy does this routing instead, so the rewrite is only added when
// API_INTERNAL_URL is set.
const apiInternalUrl = process.env.API_INTERNAL_URL;

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // Content-Security-Policy (with a per-request nonce) is set in src/proxy.ts.
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // Off on purpose: every page renders per request so it can carry a CSP nonce,
  // and Partial Prerendering is incompatible with nonces (ADR-18).
  cacheComponents: false,
  // Django's URLs end in "/"; don't let Next.js redirect them away.
  skipTrailingSlashRedirect: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    if (!apiInternalUrl) return [];
    // `:path*` drops a trailing slash, so slash-terminated URLs get their own rule.
    return [
      { source: "/api/:path*/", destination: `${apiInternalUrl}/api/:path*/` },
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
    ];
  },
};

export default nextConfig;
