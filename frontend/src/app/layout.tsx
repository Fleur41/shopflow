import type { Metadata, Viewport } from "next";
import { connection } from "next/server";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "ShopFlow", template: "%s · ShopFlow" },
  description: "Point of sale, inventory and customer credit management",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Every page renders per request so it carries this request's CSP nonce.
  await connection();
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-slate-50 text-slate-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
