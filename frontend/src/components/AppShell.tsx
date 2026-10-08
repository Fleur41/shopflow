"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useId } from "react";

import { ErrorAlert, Loading } from "@/components/ui/Feedback";
import { isSignedOutError, useLogout, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { navItemsFor } from "@/lib/nav";

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();
  const logout = useLogout();
  const [store, selectStore] = useCurrentStore(me.data);
  const storeSelectId = useId();

  useEffect(() => {
    if (isSignedOutError(me.error)) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (me.data && !me.data.organization) router.replace("/select-business");
  }, [me.error, me.data, pathname, router]);

  if (me.isPending || isSignedOutError(me.error) || (me.data && !me.data.organization)) {
    return <Loading label="Loading your business…" />;
  }
  if (me.error) {
    return (
      <main id="main" className="p-6">
        <ErrorAlert error={me.error} />
      </main>
    );
  }

  const data = me.data;
  const stores = data.access?.stores ?? [];

  async function signOut(everywhere: boolean) {
    await logout.mutateAsync(everywhere).catch(() => undefined);
    router.replace("/login");
  }

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        Skip to main content
      </a>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-lg font-bold text-emerald-800">ShopFlow</span>
          <span className="text-slate-700">{data.organization?.name}</span>
          {stores.length > 0 && (
            <div className="flex items-center gap-2 text-sm">
              <label htmlFor={storeSelectId} className="text-slate-600">
                Store
              </label>
              <select
                id={storeSelectId}
                value={store?.id ?? ""}
                onChange={(e) => selectStore(e.target.value)}
                className="min-h-11 rounded-md border border-slate-400 bg-white px-2"
              >
                {stores.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} · {s.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <details className="relative">
          <summary className="flex min-h-11 cursor-pointer list-none items-center rounded-md px-3 hover:bg-slate-100">
            {data.user.full_name} <span className="ml-2 text-sm text-slate-600">({data.access?.role.name})</span>
          </summary>
          <div className="absolute right-0 z-10 mt-1 flex w-56 flex-col rounded-md bg-white p-1 shadow-lg ring-1 ring-slate-200">
            <Link href="/account" className="rounded px-3 py-2 hover:bg-slate-100">
              Your account
            </Link>
            {data.organizations.length > 1 && (
              <Link href="/select-business" className="rounded px-3 py-2 hover:bg-slate-100">
                Switch business
              </Link>
            )}
            <button type="button" onClick={() => signOut(false)} className="rounded px-3 py-2 text-left hover:bg-slate-100">
              Sign out
            </button>
            <button type="button" onClick={() => signOut(true)} className="rounded px-3 py-2 text-left hover:bg-slate-100">
              Sign out everywhere
            </button>
          </div>
        </details>
      </header>
      <div className="flex flex-col md:flex-row">
        <nav aria-label="Main" className="border-b border-slate-200 bg-white md:min-h-[calc(100vh-4.5rem)] md:w-56 md:border-b-0 md:border-r">
          <ul className="flex gap-1 overflow-x-auto p-2 md:flex-col">
            {navItemsFor(data).map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-11 items-center whitespace-nowrap rounded-md px-3 ${active ? "bg-emerald-100 font-semibold text-emerald-900" : "hover:bg-slate-100"}`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main id="main" className="flex-1 p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
