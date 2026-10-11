import type { ProductSupplier } from "@/lib/api/types";

/** "Their code MS-1KG · Min. order 50 · 3-day lead time" (only what's set). */
export function linkTerms(link: Pick<ProductSupplier, "supplier_sku" | "min_order_qty" | "lead_time_days">): string {
  const parts: string[] = [];
  if (link.supplier_sku) parts.push(`Their code ${link.supplier_sku}`);
  if (link.min_order_qty) parts.push(`Min. order ${trimQuantity(link.min_order_qty)}`);
  if (link.lead_time_days !== null && link.lead_time_days !== undefined) {
    parts.push(link.lead_time_days === 0 ? "Same-day delivery" : `${link.lead_time_days}-day lead time`);
  }
  return parts.join(" · ");
}

/** "50.000" → "50", "2.500" → "2.5". */
function trimQuantity(quantity: string): string {
  return quantity.includes(".") ? quantity.replace(/\.?0+$/, "") : quantity;
}
