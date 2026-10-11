import { describe, expect, it } from "vitest";

import { linkTerms } from "./link-terms";

describe("linkTerms", () => {
  it("summarises only the terms that are set", () => {
    expect(linkTerms({ supplier_sku: "MS-1KG", min_order_qty: "50.000", lead_time_days: 3 })).toBe(
      "Their code MS-1KG · Min. order 50 · 3-day lead time",
    );
    expect(linkTerms({ supplier_sku: "", min_order_qty: "2.500", lead_time_days: 0 })).toBe("Min. order 2.5 · Same-day delivery");
    expect(linkTerms({ supplier_sku: "", min_order_qty: null, lead_time_days: null })).toBe("");
  });
});
