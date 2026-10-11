import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { formatAmount, priceChange } from "@/lib/money";

const SIZES = {
  sm: "text-sm",
  md: "text-base",
  lg: "text-xl",
  xl: "text-3xl tracking-tight",
  display: "text-4xl sm:text-5xl tracking-tight",
} as const;

type MoneyProps = {
  amount: string | null | undefined;
  currency: string | undefined;
  size?: keyof typeof SIZES;
  /** "signed" colours negatives; "inverse" is for dark backgrounds. */
  tone?: "default" | "signed" | "inverse";
  className?: string;
};

/**
 * An amount of money, exactly as the ledger holds it (no float rounding).
 * The currency code is quiet, whole units strong, cents lighter; figures are
 * tabular so columns of amounts line up. Screen readers get one clean string.
 */
export function Money({ amount, currency, size = "md", tone = "default", className = "" }: MoneyProps) {
  const formatted = amount && currency ? formatAmount(amount, currency) : null;
  if (!formatted) return <span className={`tabular text-slate-600 ${SIZES[size]} ${className}`}>—</span>;

  const inverse = tone === "inverse";
  const negativeTone = tone === "signed" && formatted.negative ? "text-rose-700" : "";
  const quiet = inverse ? "text-emerald-100/80" : "text-slate-600";
  return (
    <span className={`tabular inline-flex items-baseline whitespace-nowrap ${SIZES[size]} ${negativeTone} ${className}`}>
      <span className="sr-only">{formatted.text}</span>
      <span aria-hidden="true" className="inline-flex items-baseline">
        {formatted.negative && <span className="mr-0.5">−</span>}
        <span className={`mr-1 self-center text-[0.62em] font-semibold tracking-wider ${negativeTone || quiet}`}>{formatted.currency}</span>
        <span className="font-semibold">{formatted.whole}</span>
        {formatted.fraction && (
          <span className={`font-medium ${size === "display" || size === "xl" ? "text-[0.6em] self-start mt-[0.18em] ml-px" : "text-[0.9em]"} ${negativeTone || quiet}`}>
            .{formatted.fraction}
          </span>
        )}
      </span>
    </span>
  );
}

/** How a price moved: icon, amount and percentage, in words for screen readers. */
export function PriceChange({ from, to, currency }: { from: string | null | undefined; to: string; currency: string | undefined }) {
  if (!currency) return null;
  const change = priceChange(from ?? null, to, currency);
  if (from === null || from === undefined) {
    return <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">First price</span>;
  }
  const styles = {
    up: { icon: ArrowUpRight, chip: "bg-emerald-50 text-emerald-800 ring-emerald-600/20", word: "up" },
    down: { icon: ArrowDownRight, chip: "bg-rose-50 text-rose-800 ring-rose-600/20", word: "down" },
    none: { icon: Minus, chip: "bg-slate-100 text-slate-700 ring-slate-500/20", word: "unchanged" },
  }[change.direction];
  const Icon = styles.icon;
  const detail = change.direction === "none" ? "" : `${change.difference}${change.percent ? ` (${change.percent}%)` : ""}`;
  return (
    <span className={`tabular inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${styles.chip}`}>
      <Icon aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
      <span className="sr-only">Price {styles.word} </span>
      <span>{detail || "No change"}</span>
    </span>
  );
}
