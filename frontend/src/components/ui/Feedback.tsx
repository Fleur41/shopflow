import Link from "next/link";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api/errors";

export function ErrorAlert({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : "Please try again.";
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-4 text-red-900">
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm">{message}</p>
      {error instanceof ApiError && error.code === "MFA_ENROLLMENT_REQUIRED" && (
        <Link href="/account" className="mt-2 inline-block text-sm font-semibold underline">
          Set up two-step verification
        </Link>
      )}
      {requestId && <p className="mt-2 text-xs text-red-800">Reference: {requestId}</p>}
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

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-2 text-sm text-slate-600">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-950">{children}</div>;
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "success" | "warning"; children: ReactNode }) {
  const tones = {
    neutral: "bg-slate-100 text-slate-800",
    success: "bg-emerald-100 text-emerald-900",
    warning: "bg-amber-100 text-amber-900",
  };
  return <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${tones[tone]}`}>{children}</span>;
}
