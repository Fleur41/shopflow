import type { ButtonHTMLAttributes } from "react";

const variants = {
  primary: "bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-emerald-700/60",
  secondary: "bg-white text-slate-900 ring-1 ring-slate-300 hover:bg-slate-100",
  danger: "bg-red-700 text-white hover:bg-red-800 disabled:bg-red-700/60",
  ghost: "text-slate-700 hover:bg-slate-100",
} as const;

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
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
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {loading && <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}
