"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, ScanLine } from "lucide-react";
import Link from "next/link";

import { Card, Notice, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, needsTwoStep, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { navItemsFor } from "@/lib/nav";
import { MEMBERS_KEY, PRODUCTS_KEY } from "@/lib/query-keys";

const DESCRIPTIONS: Record<string, string> = {
  "/products": "Prices, barcodes and photos for everything you sell.",
  "/settings/catalog": "Categories, brands, units and tax rates.",
  "/suppliers": "Who you buy from, their contacts and what they supply.",
  "/settings/stores": "Your shop locations and their tills.",
  "/settings/staff": "Who works where, and what they may do.",
  "/settings/roles": "Permission sets for owners, managers and cashiers.",
  "/settings/payment-methods": "Cash, M-Pesa, cards: how customers pay.",
};

export default function DashboardPage() {
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const sections = navItemsFor(me).filter((item) => item.href !== "/");
  const today = new Intl.DateTimeFormat("en-KE", { weekday: "long", day: "numeric", month: "long" }).format(new Date());

  // Setup progress from what already exists; each check is skipped if the user can't see it.
  const products = useQuery({
    queryKey: [...PRODUCTS_KEY, "any"],
    queryFn: () => unwrap(api.GET("/api/v1/products/", { params: { query: { page_size: 1 } } })),
    enabled: can(me, "products.view"),
  });
  const members = useQuery({
    queryKey: [...MEMBERS_KEY, "count-hint"],
    queryFn: () => unwrap(api.GET("/api/v1/members/", { params: { query: { page_size: 2 } } })),
    enabled: can(me, "users.view"),
  });

  const steps = [
    me && (me.access?.role.template === "OWNER" || me.access?.role.template === "MANAGER")
      ? { label: "Turn on two-step verification", done: Boolean(me.mfa_verified), href: "/account" }
      : null,
    me ? { label: "Verify your email", done: me.user.email_verified, href: "/account" } : null,
    can(me, "products.manage") ? { label: "Add your first product", done: (products.data?.results.length ?? 0) > 0, href: "/products" } : null,
    can(me, "users.manage") ? { label: "Add a member of staff", done: (members.data?.results.length ?? 0) > 1, href: "/settings/staff" } : null,
  ].filter((step): step is { label: string; done: boolean; href: string } => step !== null);
  const done = steps.filter((step) => step.done).length;

  return (
    <>
      <PageHeader
        eyebrow={today}
        title={`Welcome, ${me?.user.full_name.split(" ")[0] ?? ""}`}
        description={store ? `You’re working in ${store.name} (${store.code}).` : undefined}
      />
      {needsTwoStep(me) && (
        <Notice>
          <p className="font-semibold">Protect your business with two-step verification</p>
          <p className="mt-1">You’ll need it to manage staff, stores and other sensitive settings.</p>
          <Link href="/account" className="mt-2 inline-block font-semibold underline">
            Set it up now
          </Link>
        </Notice>
      )}
      {me && !me.user.email_verified && (
        <Notice>
          <p className="font-semibold">Confirm your email address</p>
          <p className="mt-1 break-words">We sent a link to {me.user.email}. It lets you reset your password if you ever forget it.</p>
          <Link href="/account" className="mt-2 inline-block font-semibold underline">
            Resend the link
          </Link>
        </Notice>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {sections.length > 0 && (
          <section aria-labelledby="manage-heading">
            <h2 id="manage-heading" className="mb-3 text-base font-semibold tracking-tight">
              Manage your business
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2">
              {sections.map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="group flex h-full gap-4 rounded-xl bg-white p-5 shadow-card ring-1 ring-slate-200 transition hover:-translate-y-0.5 hover:shadow-raised hover:ring-emerald-600/40"
                    >
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/15">
                        <Icon aria-hidden="true" className="size-5" />
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-1 font-semibold">
                          {item.label}
                          <ArrowRight aria-hidden="true" className="size-4 text-slate-500 transition group-hover:translate-x-0.5 group-hover:text-emerald-700" />
                        </span>
                        {DESCRIPTIONS[item.href] && <span className="mt-0.5 block text-sm text-slate-600">{DESCRIPTIONS[item.href]}</span>}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div className="flex flex-col gap-6">
          {steps.length > 0 && (
            <Card title="Getting started" description={`${done} of ${steps.length} done`}>
              {/* A native progress bar: accessible, and no inline style (the CSP forbids those). */}
              <progress className="meter mb-4" value={done} max={steps.length} aria-label="Setup progress" />
              <ul className="flex flex-col gap-1">
                {steps.map((step) => (
                  <li key={step.label}>
                    <Link href={step.href} className="flex min-h-10 items-center gap-3 rounded-lg px-2 text-sm hover:bg-slate-50">
                      <span
                        aria-hidden="true"
                        className={`flex size-5 shrink-0 items-center justify-center rounded-full ${step.done ? "bg-emerald-600 text-white" : "ring-2 ring-inset ring-slate-300"}`}
                      >
                        {step.done && <Check className="size-3.5" strokeWidth={3} />}
                      </span>
                      <span className={step.done ? "text-slate-600 line-through decoration-slate-400" : "font-medium"}>{step.label}</span>
                      <span className="sr-only">{step.done ? "(done)" : "(to do)"}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <section aria-labelledby="coming-heading" className="relative overflow-hidden rounded-xl bg-ledger-900 p-6 text-white">
            <div aria-hidden className="pointer-events-none absolute -right-10 -top-10 size-40 rounded-full bg-emerald-400/20 blur-2xl" />
            <ScanLine aria-hidden="true" className="relative mb-3 size-6 text-emerald-300" />
            <h2 id="coming-heading" className="relative font-semibold">
              Coming next
            </h2>
            <p className="relative mt-1 text-sm text-emerald-50/85">Stock levels, then the till: barcode scanning, M-Pesa and cash, receipts and customer credit.</p>
          </section>
        </div>
      </div>
    </>
  );
}
