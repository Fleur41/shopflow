import type { components } from "./api/schema";

type Schemas = components["schemas"];

/** KRA eTIMS tax types; the rate each implies (docs/ETIMS.md). */
export const TAX_TYPE_LABELS: Record<Schemas["EtimsTaxTypeEnum"], string> = {
  A: "A · Exempt",
  B: "B · VAT 16%",
  C: "C · Zero-rated",
  D: "D · Non-VAT",
  E: "E · VAT 8%",
};

export const PRODUCT_TYPE_LABELS: Record<Schemas["EtimsProductTypeEnum"], string> = {
  "1": "Raw material",
  "2": "Finished product",
  "3": "Service (no stock)",
};

/** "0.1600" → "16%". */
export function formatRate(rate: string): string {
  return `${Number((Number(rate) * 100).toFixed(2))}%`;
}

/** For display only; amounts are never computed with floats (docs/PRICING.md). */
export function formatMoney(amount: string | null | undefined, currency: string | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = Number(amount);
  if (!currency) return value.toFixed(2);
  return new Intl.NumberFormat("en-KE", { style: "currency", currency }).format(value);
}
