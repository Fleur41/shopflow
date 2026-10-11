/**
 * Cart pricing for display: line totals, discounts and tax (docs/PRICING.md).
 *
 * The server's calculation is authoritative; this mirrors it so the POS can
 * show totals instantly and offline. It must pass
 * shared/pricing-test-vectors/v1.json, like the server. Arithmetic is on
 * exact BigInt values scaled to a fixed number of decimal places, never
 * floats. Field names match the API's.
 */

export type TaxMode = "INCLUSIVE" | "EXCLUSIVE";

export type LineInput = {
  quantity: string;
  unit_price: string;
  tax_rate: string;
  discount_amount?: string;
};

export type CartInput = {
  minor_units: number;
  tax_mode: TaxMode | string;
  lines: LineInput[];
  order_discount?: string;
};

export type LinePrice = {
  gross_amount: string;
  discount_amount: string;
  order_discount: string;
  tax_amount: string;
  line_total: string;
};

export type TaxSummary = { rate: string; taxable_amount: string; tax_amount: string };

export type CartPrice = {
  lines: LinePrice[];
  subtotal: string;
  discount_total: string;
  tax_total: string;
  total: string;
  taxes: TaxSummary[];
};

const QUANTITY_PLACES = 3;
const PRICE_PLACES = 4;
const RATE_PLACES = 4;
const MAX_MINOR_UNITS = 4;
const PLAIN_DECIMAL = /^(\d+)(?:\.(\d+))?$/;

export class PricingError extends Error {
  constructor(
    readonly code: string,
    readonly line: number | null = null,
  ) {
    super(line === null ? code : `${code} (line ${line})`);
    this.name = "PricingError";
  }
}

export function priceCart(cart: CartInput): CartPrice {
  const { minor_units: minorUnits, tax_mode: taxMode } = cart;
  if (
    !Number.isInteger(minorUnits) ||
    minorUnits < 0 ||
    minorUnits > MAX_MINOR_UNITS ||
    (taxMode !== "INCLUSIVE" && taxMode !== "EXCLUSIVE")
  ) {
    throw new PricingError("INVALID_SETTINGS");
  }
  const minor = 10n ** BigInt(minorUnits);
  const rateScale = 10n ** BigInt(RATE_PLACES);

  // Amounts in minor units; rates scaled by 10^RATE_PLACES.
  const parsed = cart.lines.map((line, i) => {
    const quantity = parse(line.quantity, QUANTITY_PLACES, i);
    const price = parse(line.unit_price, PRICE_PLACES, i);
    const discount = parse(line.discount_amount ?? "0", minorUnits, i);
    const rate = parse(line.tax_rate, RATE_PLACES, i);
    if (quantity === 0n) throw new PricingError("QUANTITY_NOT_POSITIVE", i);
    if (rate >= rateScale) throw new PricingError("INVALID_TAX_RATE", i);
    const gross = roundHalfUp(quantity * price * minor, 10n ** BigInt(QUANTITY_PLACES + PRICE_PLACES));
    if (discount > gross) throw new PricingError("LINE_DISCOUNT_EXCEEDS_LINE", i);
    return { gross, discount, rate, net: gross - discount };
  });

  const order = parse(cart.order_discount ?? "0", minorUnits, null);
  if (order > sum(parsed.map((l) => l.net))) throw new PricingError("ORDER_DISCOUNT_EXCEEDS_TOTAL");
  const shares = allocate(order, parsed.map((l) => l.net));

  const taxes = new Map<bigint, { taxable: bigint; tax: bigint }>();
  let taxTotal = 0n;
  let total = 0n;
  const lines: LinePrice[] = parsed.map(({ gross, discount, rate, net }, i) => {
    const share = shares[i] ?? 0n;
    const amount = net - share;
    const tax =
      taxMode === "INCLUSIVE" ? roundHalfUp(amount * rate, rateScale + rate) : roundHalfUp(amount * rate, rateScale);
    const lineTotal = taxMode === "INCLUSIVE" ? amount : amount + tax;
    const entry = taxes.get(rate) ?? { taxable: 0n, tax: 0n };
    taxes.set(rate, { taxable: entry.taxable + lineTotal - tax, tax: entry.tax + tax });
    taxTotal += tax;
    total += lineTotal;
    return {
      gross_amount: format(gross, minorUnits),
      discount_amount: format(discount, minorUnits),
      order_discount: format(share, minorUnits),
      tax_amount: format(tax, minorUnits),
      line_total: format(lineTotal, minorUnits),
    };
  });

  return {
    lines,
    subtotal: format(sum(parsed.map((l) => l.gross)), minorUnits),
    discount_total: format(sum(parsed.map((l) => l.discount)) + order, minorUnits),
    tax_total: format(taxTotal, minorUnits),
    total: format(total, minorUnits),
    taxes: [...taxes.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([rate, { taxable, tax }]) => ({
        rate: format(rate, RATE_PLACES),
        taxable_amount: format(taxable, minorUnits),
        tax_amount: format(tax, minorUnits),
      })),
  };
}

/** A plain decimal string as a BigInt scaled by 10^places. */
function parse(value: string, places: number, line: number | null): bigint {
  const match = PLAIN_DECIMAL.exec(value);
  if (!match) throw new PricingError("INVALID_NUMBER", line);
  const [, whole, fraction = ""] = match;
  if (fraction.length > places) throw new PricingError("TOO_MANY_DECIMALS", line);
  return BigInt(whole + fraction.padEnd(places, "0"));
}

/** numerator / denominator rounded half up (both non-negative). */
function roundHalfUp(numerator: bigint, denominator: bigint): bigint {
  return (2n * numerator + denominator) / (2n * denominator);
}

/** Split amount in proportion to weights by largest remainder; ties go to the earlier line. */
function allocate(amount: bigint, weights: bigint[]): bigint[] {
  const total = sum(weights);
  if (amount === 0n || total === 0n) return weights.map(() => 0n);
  const parts = weights.map((w, i) => ({ i, share: (amount * w) / total, remainder: (amount * w) % total }));
  let leftover = amount - sum(parts.map((p) => p.share));
  const byRemainder = [...parts].sort((a, b) =>
    a.remainder === b.remainder ? a.i - b.i : a.remainder > b.remainder ? -1 : 1,
  );
  for (const part of byRemainder) {
    if (leftover === 0n) break;
    part.share += 1n;
    leftover -= 1n;
  }
  return parts.map((p) => p.share);
}

function sum(values: bigint[]): bigint {
  return values.reduce((a, b) => a + b, 0n);
}

function format(value: bigint, places: number): string {
  if (places === 0) return value.toString();
  const scale = 10n ** BigInt(places);
  return `${value / scale}.${(value % scale).toString().padStart(places, "0")}`;
}
