"use client";

import { ChevronsUpDown, LogOut, Menu, Repeat, UserRound, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useId, useState } from "react";

import { BrandMark } from "@/components/BrandMark";
import { ErrorAlert, Loading } from "@/components/ui/Feedback";
import { isSignedOutError, useLogout, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { navGroupsFor } from "@/lib/nav";

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();
  const logout = useLogout();
  const [store, selectStore] = useCurrentStore(me.data);
  const storeSelectId = useId();
  const navId = useId();
  // The small-screen menu remembers the page it was opened on, so navigating closes it.
  const [menuOpenOn, setMenuOpenOn] = useState<string | null>(null);
  const menuOpen = menuOpenOn === pathname;

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
  const initials = data.user.full_name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

  async function signOut(everywhere: boolean) {
    await logout.mutateAsync(everywhere).catch(() => undefined);
    router.replace("/login");
  }

  return (
    <div className="min-h-screen md:grid md:grid-cols-[16.5rem_1fr] md:bg-[linear-gradient(to_right,var(--color-ledger-900)_16.5rem,transparent_16.5rem)]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        Skip to main content
      </a>

      <aside className="relative z-20 flex flex-col bg-ledger-900 text-white md:sticky md:top-0 md:h-screen">
        {/* Brand and business */}
        <div className="flex items-center justify-between gap-3 px-4 py-4 md:px-5 md:pt-6">
          <div className="flex min-w-0 items-center gap-3">
            <BrandMark className="size-9 shrink-0" />
            <div className="min-w-0">
              <p className="text-[0.9375rem] font-semibold leading-tight tracking-tight">ShopFlow</p>
              <p className="truncate text-xs text-emerald-100/80">{data.organization?.name}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setMenuOpenOn(menuOpen ? null : pathname)}
            aria-expanded={menuOpen}
            aria-controls={navId}
            className="flex size-11 items-center justify-center rounded-lg text-emerald-50 hover:bg-white/10 md:hidden"
          >
            {menuOpen ? <X aria-hidden="true" className="size-5" /> : <Menu aria-hidden="true" className="size-5" />}
            <span className="sr-only">Menu</span>
          </button>
        </div>

        <div id={navId} className={`${menuOpen ? "flex" : "hidden"} min-h-0 flex-1 flex-col md:flex`}>
          {stores.length > 0 && (
            <div className="px-4 pb-2 md:px-5">
              <label htmlFor={storeSelectId} className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-emerald-100/80">
                Store
              </label>
              <div className="relative">
                <select
                  id={storeSelectId}
                  value={store?.id ?? ""}
                  onChange={(e) => selectStore(e.target.value)}
                  className="min-h-11 w-full appearance-none rounded-lg bg-white/10 py-2 pl-3 pr-9 text-base font-medium text-white ring-1 ring-inset ring-white/15 hover:bg-white/15 [&>option]:text-slate-900"
                >
                  {stores.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.code} · {s.name}
                    </option>
                  ))}
                </select>
                <ChevronsUpDown aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-emerald-100/80" />
              </div>
            </div>
          )}

          <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
            {navGroupsFor(data).map(({ group, items }) => (
              <div key={group} className="mb-4">
                <p className="px-2 pb-1 text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-emerald-100/70" aria-hidden="true">
                  {group}
                </p>
                <ul className="flex flex-col gap-0.5">
                  {items.map((item) => {
                    const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                    const Icon = item.icon;
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={active ? "page" : undefined}
                          className={`group relative flex min-h-11 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors ${
                            active ? "bg-white/12 text-white" : "text-emerald-50/90 hover:bg-white/7 hover:text-white"
                          }`}
                        >
                          {active && <span aria-hidden className="absolute -left-3 top-2 bottom-2 w-1 rounded-r-full bg-emerald-400" />}
                          <Icon aria-hidden="true" className={`size-[1.125rem] ${active ? "text-emerald-300" : "text-emerald-100/70 group-hover:text-emerald-200"}`} />
                          {item.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>

          {/* Account */}
          <details className="group/menu relative border-t border-white/10 px-3 py-3">
            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 rounded-lg px-2 hover:bg-white/7 [&::-webkit-details-marker]:hidden">
              <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-full bg-emerald-400/20 text-xs font-semibold text-emerald-100 ring-1 ring-emerald-300/30">
                {initials}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{data.user.full_name}</span>
                <span className="block truncate text-xs text-emerald-100/75">{data.access?.role.name}</span>
              </span>
              <ChevronsUpDown aria-hidden="true" className="size-4 text-emerald-100/70" />
            </summary>
            <div className="absolute bottom-full left-3 right-3 z-30 mb-1 flex flex-col rounded-xl bg-white p-1.5 text-sm text-slate-800 shadow-raised ring-1 ring-slate-900/10">
              <Link href="/account" className="flex items-center gap-2 rounded-lg min-h-11 px-3 py-2 hover:bg-slate-100">
                <UserRound aria-hidden="true" className="size-4 text-slate-600" /> Your account
              </Link>
              {data.organizations.length > 1 && (
                <Link href="/select-business" className="flex items-center gap-2 rounded-lg min-h-11 px-3 py-2 hover:bg-slate-100">
                  <Repeat aria-hidden="true" className="size-4 text-slate-600" /> Switch business
                </Link>
              )}
              <hr className="my-1 border-slate-100" />
              <button type="button" onClick={() => signOut(false)} className="flex items-center gap-2 rounded-lg min-h-11 px-3 py-2 text-left hover:bg-slate-100">
                <LogOut aria-hidden="true" className="size-4 text-slate-600" /> Sign out
              </button>
              <button type="button" onClick={() => signOut(true)} className="flex items-center gap-2 rounded-lg min-h-11 px-3 py-2 text-left hover:bg-slate-100">
                <LogOut aria-hidden="true" className="size-4 text-slate-600" /> Sign out everywhere
              </button>
            </div>
          </details>
        </div>
      </aside>

      <main id="main" className="min-w-0 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  );
}
