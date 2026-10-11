import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { connection } from "next/server";

import "./globals.css";
import { Providers } from "./providers";

// Downloaded at build time and served from our own origin: no request ever
// goes to Google, and the CSP's font-src 'self' holds (docs/SECURITY.md §5).
const inter = Inter({ subsets: ["latin"], display: "swap", variable: "--font-inter" });

export const metadata: Metadata = {
  title: { default: "ShopFlow", template: "%s · ShopFlow" },
  description: "Point of sale, inventory and customer credit management",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0a2f27",
  // The on-screen keyboard shrinks the page instead of covering it, so forms
  // and dialogs keep their buttons reachable while typing.
  interactiveWidget: "resizes-content",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Every page renders per request so it carries this request's CSP nonce.
  await connection();
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full bg-canvas font-sans text-slate-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
