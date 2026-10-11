import { LockKeyhole, ReceiptText, ScanLine } from "lucide-react";

import { BrandMark } from "@/components/BrandMark";

const POINTS = [
  { icon: ScanLine, title: "Sell in seconds", text: "Scan, take cash or M-Pesa, print the receipt." },
  { icon: ReceiptText, title: "Every shilling traced", text: "Stock, prices and customer credit, all with an audit trail." },
  { icon: LockKeyhole, title: "Yours alone", text: "Two-step sign-in and staff who see only their store." },
];

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <aside className="relative hidden overflow-hidden bg-ledger-900 px-12 py-14 text-white lg:flex lg:flex-col lg:justify-between">
        {/* A faint ledger grid: ruled paper, the oldest money interface. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:linear-gradient(to_right,white_1px,transparent_1px),linear-gradient(to_bottom,white_1px,transparent_1px)] [background-size:44px_44px]"
        />
        <div aria-hidden="true" className="pointer-events-none absolute -right-32 -top-32 size-[28rem] rounded-full bg-emerald-400/15 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <BrandMark className="size-10" />
          <span className="text-lg font-semibold tracking-tight">ShopFlow</span>
        </div>
        <div className="relative max-w-md">
          <p className="text-4xl font-semibold leading-tight tracking-tight">Every shilling, accounted for.</p>
          <p className="mt-4 text-lg text-emerald-50/85">The till, the stock room and the credit book, in one place your whole team can trust.</p>
          <ul className="mt-10 flex flex-col gap-5">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15">
                  <Icon aria-hidden="true" className="size-5 text-emerald-300" />
                </span>
                <span>
                  <span className="block font-semibold">{title}</span>
                  <span className="block text-sm text-emerald-50/80">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-emerald-50/70">Made for shops in Kenya and beyond.</p>
      </aside>

      <main id="main" className="flex min-h-screen items-start justify-center bg-canvas px-4 py-12 sm:items-center">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center justify-center gap-2.5 lg:hidden">
            <BrandMark className="size-9" />
            <span className="text-xl font-semibold tracking-tight text-ledger-900">ShopFlow</span>
          </div>
          <div className="rounded-2xl bg-white p-6 shadow-raised ring-1 ring-slate-900/5 sm:p-8">{children}</div>
        </div>
      </main>
    </div>
  );
}
