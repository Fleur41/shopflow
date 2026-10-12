import { describe, expect, it } from "vitest";

import type { Lookup } from "./api/types";
import {
  type CartLine,
  addToCart,
  cashShortcuts,
  fromScaled,
  priceLines,
  quantityProblem,
  repriceLines,
  shortOfStock,
  stepQuantity,
  summariseTenders,
  toScaled,
  type Tender,
} from "./cart";

function lookup(overrides: Partial<Lookup> = {}): Lookup {
  return {
    product_id: "milk",
    name: "Milk 500ml",
    sku: "MILK",
    unit: { code: "PCS", name: "Pieces", allows_fraction: false },
    tax_rate: "0.1600",
    price: "80.0000",
    pack_quantity: "1.000",
    track_inventory: true,
    quantity_on_hand: "3.000",
    is_active: true,
    thumbnail_url: null,
    ...overrides,
  };
}

describe("decimal helpers", () => {
  it("scale and unscale exactly", () => {
    expect(toScaled("1.25", 3)).toBe(1250n);
    expect(toScaled("1.2345", 3)).toBeNull();
    expect(toScaled("-1", 3)).toBeNull();
    expect(fromScaled(2000n, 3)).toBe("2");
    expect(fromScaled(1250n, 3)).toBe("1.25");
    expect(fromScaled(28000n, 2, { trim: false })).toBe("280.00");
  });
});

describe("cart", () => {
  it("merges rescans and adds pack quantities", () => {
    let cart: CartLine[] = [];
    cart = addToCart(cart, lookup(), "6161000000017");
    cart = addToCart(cart, lookup(), "6161000000017");
    cart = addToCart(cart, lookup({ pack_quantity: "12.000" }), "6161000000024");
    expect(cart).toHaveLength(1);
    expect(cart[0]?.quantity).toBe("14");
    expect(cart[0]?.scannedCode).toBe("6161000000024");
  });

  it("keeps whole units whole, unless sold by weight", () => {
    const [milk] = addToCart([], lookup(), "");
    const [rice] = addToCart([], lookup({ product_id: "rice", unit: { code: "KG", name: "Kilogram", allows_fraction: true } }), "");
    expect(quantityProblem(milk as CartLine, "1.5")).toMatch(/whole units/);
    expect(quantityProblem(rice as CartLine, "1.5")).toBeNull();
    expect(quantityProblem(rice as CartLine, "0")).toMatch(/above 0/);
  });

  it("steps quantities but never below one", () => {
    const cart = addToCart([], lookup(), "");
    expect(stepQuantity(cart, 0, -1)[0]?.quantity).toBe("1");
    expect(stepQuantity(cart, 0, 1)[0]?.quantity).toBe("2");
  });

  it("prices like the server and warns when stock runs short", () => {
    let cart = addToCart([], lookup(), "");
    cart = stepQuantity(stepQuantity(cart, 0, 1), 0, 1); // 3
    expect(priceLines(cart, 2, "INCLUSIVE")?.total).toBe("240.00");
    expect(shortOfStock(cart[0] as CartLine)).toBe(false);
    cart = stepQuantity(cart, 0, 1);
    expect(shortOfStock(cart[0] as CartLine)).toBe(true);
    expect(priceLines(repriceLines(cart, { milk: "75.0000" }), 2, "INCLUSIVE")?.total).toBe("300.00");
  });
});

describe("tenders", () => {
  const cash: Tender = { methodId: "c", name: "Cash", kind: "CASH", requiresReference: false, amount: "", tendered: "", reference: "" };
  const mpesa: Tender = { methodId: "m", name: "M-Pesa", kind: "MOBILE_MONEY", requiresReference: true, amount: "", tendered: "", reference: "" };

  it("works out what's left and the change", () => {
    const summary = summariseTenders("220.00", [{ ...cash, amount: "220.00", tendered: "500" }], "", 2);
    expect(summary).toEqual({ remaining: "0.00", change: "280.00", complete: true, problems: {} });
  });

  it("splits between cash, M-Pesa and credit", () => {
    const split = [
      { ...cash, amount: "40" },
      { ...mpesa, amount: "100", reference: "" },
    ];
    const missingCode = summariseTenders("240.00", split, "100", 2);
    expect(missingCode.remaining).toBe("0.00");
    expect(missingCode.complete).toBe(false);
    expect(missingCode.problems[1]).toMatch(/M-Pesa code/);
    split[1] = { ...mpesa, amount: "100", reference: "QA12BC34DE" };
    expect(summariseTenders("240.00", split, "100", 2).complete).toBe(true);
    expect(summariseTenders("240.00", split, "", 2).remaining).toBe("100.00");
  });

  it("offers round notes above the amount", () => {
    expect(cashShortcuts("220.00", 2)).toEqual(["250.00", "300.00", "400.00", "500.00"]);
    expect(cashShortcuts("1000.00", 2)).toEqual([]);
  });
});
