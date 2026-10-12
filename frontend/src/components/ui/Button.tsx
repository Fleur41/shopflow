import type { ComponentProps } from "react";

const variants = {
  primary:
    "bg-emerald-700 text-white shadow-sm shadow-emerald-950/20 hover:bg-emerald-800 active:bg-emerald-900 disabled:bg-emerald-700/60",
  secondary: "bg-white text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50 hover:ring-slate-400 active:bg-slate-100",
  danger: "bg-rose-700 text-white shadow-sm hover:bg-rose-800 active:bg-rose-900 disabled:bg-rose-700/60",
  ghost: "text-slate-700 hover:bg-slate-100 active:bg-slate-200",
} as const;

type Props = ComponentProps<"button"> & {
  variant?: keyof typeof variants;
  loading?: boolean;
};

export function Button({ variant = "primary", loading = false, className = "", children, disabled, ...props }: Props) {
  return (
    <button
      type="button"
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-[background-color,box-shadow,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:active:translate-y-0 ${variants[variant]} ${className}`}
    >
      {loading && <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}
