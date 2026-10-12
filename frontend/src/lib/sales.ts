"use client";

import { useSearchParams } from "next/navigation";

import type { Me } from "./api/types";
import { useCurrentStore } from "./current-store";
import { formatAmount } from "./money";

/** The store a sale page is about: ``?store=`` (links from the till), else the current store. */
export function useSaleStoreId(me: Me | undefined): string | null {
  const fromUrl = useSearchParams().get("store");
  const [current] = useCurrentStore(me);
  return fromUrl ?? current?.id ?? null;
}

/** "12 Oct 2026, 18:04" in the business's time zone. */
export function formatDateTime(iso: string, timeZone: string | undefined): string {
  return new Intl.DateTimeFormat("en-KE", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timeZone || undefined,
  }).format(new Date(iso));
}

/** "1,234.50": an amount without its currency, for receipts and dense tables. */
export function plainAmount(amount: string, currency: string): string {
  const formatted = formatAmount(amount, currency);
  if (!formatted) return amount;
  const number = formatted.fraction ? `${formatted.whole}.${formatted.fraction}` : formatted.whole;
  return formatted.negative ? `-${number}` : number;
}

/** "2", "1.25": a quantity without trailing zeros. */
export function plainQuantity(quantity: string): string {
  return quantity.includes(".") ? quantity.replace(/\.?0+$/, "") : quantity;
}

export const METHOD_LABELS: Record<string, string> = { CASH: "Cash", MOBILE_MONEY: "Mobile money", CARD: "Card" };
