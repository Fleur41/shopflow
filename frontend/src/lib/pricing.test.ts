import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { type CartInput, PricingError, priceCart } from "./pricing";

type Case = {
  name: string;
  input: CartInput;
  expected?: unknown;
  expected_error?: { code: string; line: number | null };
};

// frontend/ → repository root. In Docker, /app/.. is /, so this resolves to the /shared mount.
const VECTORS = resolve(process.cwd(), "..", "shared", "pricing-test-vectors", "v1.json");
const { cases } = JSON.parse(readFileSync(VECTORS, "utf8")) as { cases: Case[] };

describe("priceCart passes the shared pricing vectors", () => {
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    if (c.expected_error) {
      let error: unknown;
      try {
        priceCart(c.input);
      } catch (e) {
        error = e;
      }
      expect(error).toBeInstanceOf(PricingError);
      const { code, line } = error as PricingError;
      expect({ code, line }).toEqual(c.expected_error);
    } else {
      expect(priceCart(c.input)).toEqual(c.expected);
    }
  });
});
