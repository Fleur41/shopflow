/**
 * The till's cart and tenders, as plain data and pure functions.
 *
 * Quantities and money are decimal strings and all arithmetic is on BigInt,
 * never floats, so the total on screen is the total the server computes
 * (docs/PRICING.md). The server re-prices everything; this is for display.
 */
import type { Lookup } from "./api/types";
import { type CartPrice, priceCart } from "./pricing";

export type CartLine = {
  productId: string;
  name: string;
  sku: string;
  unitCode: string;
  allowsFraction: boolean;
  /** The store's price, as the API sent it ("80.0000"). */
  unitPrice: string;
  taxRate: string;
  /** "2", "1.25" */
  quantity: string;
  /** The last code scanned for this line, kept on the sale for audits. */
  scannedCode: string;
  trackInventory: boolean;
  /** Stock when the product was looked up; null for services. */
  onHand: string | null;
  thumbnailUrl: string | null;
};

const QUANTITY_PLACES = 3;
const DECIMAL = /^(\d+)(?:\.(\d+))?$/;

/** A non-negative decimal string as an integer scaled by 10^places, or null. */
export function toScaled(value: string, places: number): bigint | null {
  const match = DECIMAL.exec(value.trim());
  if (!match) return null;
  const [, whole = "0", fraction = ""] = match;
  if (fraction.length > places) return null;
  return BigInt(whole + fraction.padEnd(places, "0"));
}

/** An integer scaled by 10^places as a plain decimal string ("1.25", "2"). */
export function fromScaled(value: bigint, places: number, { trim = true } = {}): string {
  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(places + 1, "0");
  let text = places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits;
  if (trim && places) text = text.replace(/\.?0+$/, "");
  return negative ? `-${text}` : text;
}

/** Add a looked-up product (one scan) to the cart: the same product goes on the same line. */
export function addToCart(lines: CartLine[], found: Lookup, scannedCode: string): CartLine[] {
  const pack = toScaled(found.pack_quantity, QUANTITY_PLACES) ?? 1000n;
  const existing = lines.findIndex((line) => line.productId === found.product_id && line.unitPrice === found.price);
  if (existing >= 0) {
    return lines.map((line, index) =>
      index === existing
        ? { ...line, quantity: fromScaled((toScaled(line.quantity, QUANTITY_PLACES) ?? 0n) + pack, QUANTITY_PLACES), scannedCode: scannedCode || line.scannedCode }
        : line,
    );
  }
  return [
    ...lines,
    {
      productId: found.product_id,
      name: found.name,
      sku: found.sku,
      unitCode: found.unit.code,
      allowsFraction: found.unit.allows_fraction,
      unitPrice: found.price,
      taxRate: found.tax_rate,
      quantity: fromScaled(pack, QUANTITY_PLACES),
      scannedCode,
      trackInventory: found.track_inventory,
      onHand: found.quantity_on_hand ?? null,
      thumbnailUrl: found.thumbnail_url ?? null,
    },
  ];
}

/** Whether a typed quantity is valid for the line: above 0, whole unless sold by weight/volume. */
export function quantityProblem(line: CartLine, quantity: string): string | null {
  const scaled = toScaled(quantity, QUANTITY_PLACES);
  if (scaled === null) return "Enter a number, up to 3 decimals.";
  if (scaled <= 0n) return "Enter a quantity above 0.";
  if (!line.allowsFraction && scaled % 1000n !== 0n) return `${line.name} is sold in whole units.`;
  return null;
}

export function setQuantity(lines: CartLine[], index: number, quantity: string): CartLine[] {
  return lines.map((line, i) => (i === index ? { ...line, quantity } : line));
}

/** One more or one less (by 1 unit); never below 1 for whole units. */
export function stepQuantity(lines: CartLine[], index: number, step: 1 | -1): CartLine[] {
  return lines.map((line, i) => {
    if (i !== index) return line;
    const current = toScaled(line.quantity, QUANTITY_PLACES) ?? 1000n;
    const next = current + BigInt(step) * 1000n;
    return next < 1000n ? line : { ...line, quantity: fromScaled(next, QUANTITY_PLACES) };
  });
}

export function removeLine(lines: CartLine[], index: number): CartLine[] {
  return lines.filter((_, i) => i !== index);
}

/** Apply new prices the server reported (409 PRICE_CHANGED): productId → price. */
export function repriceLines(lines: CartLine[], prices: Record<string, string>): CartLine[] {
  return lines.map((line) => (prices[line.productId] ? { ...line, unitPrice: prices[line.productId] as string } : line));
}

/** Stock the cart would leave, when it would go below zero (a warning; the server decides). */
export function shortOfStock(line: CartLine): boolean {
  if (!line.trackInventory || line.onHand === null) return false;
  const onHand = toScaled(line.onHand.replace(/^-/, ""), QUANTITY_PLACES) ?? 0n;
  const signedOnHand = line.onHand.startsWith("-") ? -onHand : onHand;
  return (toScaled(line.quantity, QUANTITY_PLACES) ?? 0n) > signedOnHand;
}

/** Price the cart like the server, or null while a quantity is invalid. */
export function priceLines(lines: CartLine[], minorUnits: number, taxMode: string): CartPrice | null {
  if (lines.length === 0 || lines.some((line) => quantityProblem(line, line.quantity))) return null;
  try {
    return priceCart({
      minor_units: minorUnits,
      tax_mode: taxMode,
      lines: lines.map((line) => ({ quantity: line.quantity, unit_price: line.unitPrice, tax_rate: line.taxRate })),
    });
  } catch {
    return null;
  }
}

// --- Tenders ---------------------------------------------------------------------------------

export type TenderKind = "CASH" | "CARD" | "MOBILE_MONEY" | "BANK_TRANSFER" | "OTHER";

export type Tender = {
  methodId: string;
  name: string;
  kind: TenderKind;
  requiresReference: boolean;
  /** What this tender pays towards the sale ("220.00"). */
  amount: string;
  /** Cash only: what the customer handed over. */
  tendered: string;
  reference: string;
};

export type TenderSummary = {
  /** Still to pay; "0.00" when covered. */
  remaining: string;
  change: string;
  /** Every tender is valid and they add up to the total. */
  complete: boolean;
  problems: Record<number, string>;
};

/** How much is still owed and the change due, from the total, tenders and credit. */
export function summariseTenders(total: string, tenders: Tender[], credit: string, minorUnits: number): TenderSummary {
  const due = toScaled(total, minorUnits) ?? 0n;
  const onCredit = credit ? (toScaled(credit, minorUnits) ?? 0n) : 0n;
  const problems: Record<number, string> = {};
  let paid = 0n;
  let change = 0n;
  tenders.forEach((tender, index) => {
    const amount = toScaled(tender.amount, minorUnits);
    if (amount === null || amount <= 0n) {
      problems[index] = "Enter an amount.";
      return;
    }
    paid += amount;
    if (tender.kind === "CASH" && tender.tendered) {
      const given = toScaled(tender.tendered, minorUnits);
      if (given === null) problems[index] = "Enter the cash given.";
      else if (given < amount) problems[index] = "Less than the amount.";
      else change += given - amount;
    }
    if (tender.requiresReference && !tender.reference.trim()) problems[index] = `Enter the ${tender.name} code.`;
  });
  const remaining = due - paid - onCredit;
  return {
    remaining: fromScaled(remaining > 0n ? remaining : 0n, minorUnits, { trim: false }),
    change: fromScaled(change, minorUnits, { trim: false }),
    complete: remaining === 0n && Object.keys(problems).length === 0,
    problems,
  };
}

/** Cash notes and coins worth offering as "cash given" shortcuts above an amount. */
export function cashShortcuts(amount: string, minorUnits: number): string[] {
  const due = toScaled(amount, minorUnits);
  if (due === null || due <= 0n) return [];
  const unit = 10n ** BigInt(minorUnits);
  const notes = [50n, 100n, 200n, 500n, 1000n].map((note) => note * unit);
  const ups = new Set<bigint>();
  for (const note of notes) {
    const rounded = ((due + note - 1n) / note) * note;
    if (rounded > due) ups.add(rounded);
  }
  return [...ups]
    .sort((a, b) => (a < b ? -1 : 1))
    .slice(0, 4)
    .map((value) => fromScaled(value, minorUnits, { trim: false }));
}
