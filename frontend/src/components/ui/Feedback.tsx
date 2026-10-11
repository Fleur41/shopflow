import { AlertTriangle, CircleAlert, Inbox, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api/errors";

export function ErrorAlert({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : "Please try again.";
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-red-900">
      <CircleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-red-700" />
      <div>
        <p className="font-semibold">{title}</p>
        <p className="mt-1 text-sm">{message}</p>
        {error instanceof ApiError && error.code === "MFA_ENROLLMENT_REQUIRED" && (
          <Link href="/account" className="mt-2 inline-block text-sm font-semibold underline">
            Set up two-step verification
          </Link>
        )}
        {requestId && <p className="tabular mt-2 text-xs text-red-800">Reference: {requestId}</p>}
      </div>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 p-6 text-slate-700">
      <span aria-hidden className="size-5 animate-spin rounded-full border-2 border-emerald-700 border-t-transparent" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, icon: Icon = Inbox, children }: { title: string; icon?: LucideIcon; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      <span className="mb-3 flex size-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 ring-8 ring-emerald-50/50">
        <Icon aria-hidden="true" className="size-6" />
      </span>
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-600">{children}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
}: {
  title: string;
  description?: ReactNode;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-emerald-800">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-slate-950 sm:text-[1.75rem]">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
      <AlertTriangle aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-amber-700" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** A status label with a dot; the text carries the meaning, the colour supports it. */
export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "success" | "warning"; children: ReactNode }) {
  const tones = {
    neutral: { chip: "bg-slate-100 text-slate-700 ring-slate-500/15", dot: "bg-slate-400" },
    success: { chip: "bg-emerald-50 text-emerald-800 ring-emerald-600/20", dot: "bg-emerald-600" },
    warning: { chip: "bg-amber-50 text-amber-900 ring-amber-600/25", dot: "bg-amber-500" },
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${tones.chip}`}>
      <span aria-hidden className={`size-1.5 rounded-full ${tones.dot}`} />
      {children}
    </span>
  );
}

/** A titled surface for a group of related content. */
export function Card({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const headingId = title ? `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-heading` : undefined;
  return (
    <section aria-labelledby={headingId} className={`rounded-xl bg-white p-5 shadow-card ring-1 ring-slate-200 sm:p-6 ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {title && (
              <h2 id={headingId} className="text-base font-semibold tracking-tight text-slate-950">
                {title}
              </h2>
            )}
            {description && <p className="mt-0.5 text-sm text-slate-600">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
