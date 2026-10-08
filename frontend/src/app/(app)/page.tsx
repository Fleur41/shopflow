"use client";

import Link from "next/link";

import { PageHeader } from "@/components/ui/Feedback";
import { useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { navItemsFor } from "@/lib/nav";

export default function DashboardPage() {
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const sections = navItemsFor(me).filter((item) => item.href !== "/");

  return (
    <>
      <PageHeader
        title={`Welcome, ${me?.user.full_name.split(" ")[0] ?? ""}`}
        description={store ? `You're working in ${store.name} (${store.code}).` : undefined}
      />
      {sections.length > 0 && (
        <section aria-labelledby="manage-heading" className="mb-8">
          <h2 id="manage-heading" className="mb-3 text-lg font-semibold">
            Manage your business
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {sections.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="block rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200 hover:ring-emerald-600">
                  <span className="font-semibold">{item.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="coming-heading" className="rounded-lg bg-white p-5 ring-1 ring-slate-200">
        <h2 id="coming-heading" className="font-semibold">
          Coming next
        </h2>
        <p className="mt-1 text-slate-700">
          Products and stock, then the point-of-sale screen with barcode scanning, customer credit and reports.
        </p>
      </section>
    </>
  );
}
