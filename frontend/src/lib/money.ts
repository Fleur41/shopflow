/**
 * Exact money display. The API sends amounts as decimal strings
 * ("1234.5000"); they are formatted here without ever becoming floats, so
 * what the screen shows is exactly what the ledger holds (docs/PRICING.md).
 */

const AMOUNT = /^([+-]?)(\d+)(?:\.(\d+))?$/;
const digitsCache = new Map<string, number>();

/** The currency's minor-unit digits from ISO 4217 (KES 2, UGX 0, KWD 3). */
export function minorUnits(currency: string): number {
  let digits = digitsCache.get(currency);
  if (digits === undefined) {
    try {
      digits = new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
    } catch {
      digits = 2; // an unknown code: show cents rather than fail
    }
    digitsCache.set(currency, digits);
  }
  return digits;
}

export type FormattedAmount = {
  negative: boolean;
  /** "1,234" */
  whole: string;
  /** "50", or "" for currencies without minor units */
  fraction: string;
  currency: string;
  /** "KES 1,234.50" or "−KES 1,234.50", for screen readers and plain text */
  text: string;
};

/** Round half up to the currency's minor units and group thousands. */
export function formatAmount(amount: string, currency: string): FormattedAmount | null {
  const match = AMOUNT.exec(amount.trim());
  if (!match) return null;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const digits = minorUnits(currency);
  const scaled = roundToDigits(BigInt(whole + fraction), fraction.length, digits);
  const negative = sign === "-" && scaled !== 0n;
  const text = scaled.toString().padStart(digits + 1, "0");
  const wholePart = group(digits ? text.slice(0, -digits) : text);
  const fractionPart = digits ? text.slice(-digits) : "";
  const number = fractionPart ? `${wholePart}.${fractionPart}` : wholePart;
  return {
    negative,
    whole: wholePart,
    fraction: fractionPart,
    currency,
    text: `${negative ? "−" : ""}${currency} ${number}`,
  };
}

export type PriceChange = {
  direction: "up" | "down" | "none";
  /** The absolute difference, at the currency's precision: "5.00" */
  difference: string;
  /** One decimal, absolute: "3.3"; null when there was no earlier price or it was 0 */
  percent: string | null;
};

/** How a price moved from ``before`` to ``after``, computed exactly. */
export function priceChange(before: string | null, after: string, currency: string): PriceChange {
  const scale = 4; // the API's money precision
  const next = toScaled(after, scale);
  const previous = before === null ? null : toScaled(before, scale);
  if (next === null || previous === null) return { direction: "none", difference: "", percent: null };
  const diff = next - previous;
  const magnitude = diff < 0n ? -diff : diff;
  const difference = formatAmount(`${magnitude / 10n ** BigInt(scale)}.${(magnitude % 10n ** BigInt(scale)).toString().padStart(scale, "0")}`, currency);
  // percent with one decimal = |diff| * 1000 / previous, rounded half up
  const percent = previous > 0n ? roundDiv(magnitude * 1000n, previous) : null;
  return {
    direction: diff > 0n ? "up" : diff < 0n ? "down" : "none",
    difference: difference ? (difference.fraction ? `${difference.whole}.${difference.fraction}` : difference.whole) : "",
    percent: percent === null ? null : `${percent / 10n}.${percent % 10n}`,
  };
}

/** Normalise a typed amount on blur: "150" → "150.00", "12.5" → "12.50". Leaves anything else alone. */
export function normaliseTypedAmount(value: string, currency: string): string {
  const match = /^\s*(\d+)(?:\.(\d*))?\s*$/.exec(value);
  if (!match) return value;
  const [, whole = "0", fraction = ""] = match;
  const digits = minorUnits(currency);
  if (fraction.length > digits) return value.trim(); // more precision than the currency: let the server decide
  const wholePart = whole.replace(/^0+(?=\d)/, "");
  return digits ? `${wholePart}.${fraction.padEnd(digits, "0")}` : wholePart;
}

function toScaled(amount: string, scale: number): bigint | null {
  const match = AMOUNT.exec(amount.trim());
  if (!match) return null;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const value = roundToDigits(BigInt(whole + fraction), fraction.length, scale);
  return sign === "-" ? -value : value;
}

/** ``value`` has ``from`` decimals; return it with ``to`` decimals, rounding half up. */
function roundToDigits(value: bigint, from: number, to: number): bigint {
  if (from <= to) return value * 10n ** BigInt(to - from);
  return roundDiv(value, 10n ** BigInt(from - to));
}

function roundDiv(numerator: bigint, denominator: bigint): bigint {
  return (2n * numerator + denominator) / (2n * denominator);
}

function group(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
