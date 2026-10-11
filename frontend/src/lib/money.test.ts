import { describe, expect, it } from "vitest";

import { formatAmount, minorUnits, normaliseTypedAmount, priceChange } from "./money";

describe("formatAmount", () => {
  it.each([
    ["1234.5000", "KES", "KES 1,234.50"],
    ["0.0050", "KES", "KES 0.01"], // half up, exactly
    ["0.0049", "KES", "KES 0.00"],
    ["1234567.8900", "KES", "KES 1,234,567.89"],
    ["999.5000", "UGX", "UGX 1,000"], // no minor units
    ["-60.0000", "KES", "−KES 60.00"],
    ["-0.0001", "KES", "KES 0.00"], // never a negative zero
    ["0.1 ", "USD", "USD 0.10"],
  ])("%s %s → %s", (amount, currency, text) => {
    expect(formatAmount(amount, currency)?.text).toBe(text);
  });

  it("splits whole and fraction for display", () => {
    expect(formatAmount("1234.5", "KES")).toMatchObject({ whole: "1,234", fraction: "50", negative: false });
  });

  it("is exact where floats are not", () => {
    // 0.1 + 0.2 territory: a float would print 1.0049999999999999 → 1.00
    expect(formatAmount("1.005", "KES")?.text).toBe("KES 1.01");
    expect(formatAmount("123456789012345678.995", "KES")?.text).toBe("KES 123,456,789,012,345,679.00");
  });

  it("refuses what isn't an amount", () => {
    expect(formatAmount("12,5", "KES")).toBeNull();
    expect(formatAmount("abc", "KES")).toBeNull();
  });
});

describe("minorUnits", () => {
  it("follows ISO 4217", () => {
    expect([minorUnits("KES"), minorUnits("UGX"), minorUnits("KWD")]).toEqual([2, 0, 3]);
  });
});

describe("priceChange", () => {
  it("measures a rise and a fall exactly", () => {
    expect(priceChange("150.0000", "155.0000", "KES")).toEqual({ direction: "up", difference: "5.00", percent: "3.3" });
    expect(priceChange("80.0000", "60.0000", "KES")).toEqual({ direction: "down", difference: "20.00", percent: "25.0" });
  });

  it("has no percentage for a first price or a free item", () => {
    expect(priceChange(null, "60.0000", "KES")).toMatchObject({ direction: "none", percent: null });
    expect(priceChange("0.0000", "10.0000", "KES")).toMatchObject({ direction: "up", percent: null });
  });
});

describe("normaliseTypedAmount", () => {
  it.each([
    ["150", "150.00"],
    ["12.5", "12.50"],
    ["007.1", "7.10"],
    [" 3. ", "3.00"],
    ["1.005", "1.005"], // more precise than KES: left for the server to judge
    ["12a", "12a"],
  ])("%s → %s", (typed, normalised) => {
    expect(normaliseTypedAmount(typed, "KES")).toBe(normalised);
  });

  it("uses the currency's precision", () => {
    expect(normaliseTypedAmount("1500", "UGX")).toBe("1500");
  });
});
