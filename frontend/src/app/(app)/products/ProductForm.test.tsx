import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Product } from "@/lib/api/types";

import { percentToFraction } from "../settings/catalog/LookupForms";
import { ProductForm } from "./ProductForm";

const json = (status: number, body: object) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const page = (results: object[]) => ({ next: null, previous: null, results });

const MILK: Product = {
  id: "0192f0aa-0000-7000-8000-0000000000a1",
  sku: "MILK-500",
  name: "Milk 500ml",
  category: null,
  brand: null,
  unit: "u1",
  tax_rate: "t-exempt",
  selling_price: "60.0000",
  default_cost: null,
  default_reorder_level: null,
  track_inventory: true,
  etims_product_type: "2",
  etims_item_class_code: "",
  etims_item_code: "",
  identifiers: [],
  image_url: null,
  thumbnail_url: null,
  row_version: 7,
  is_active: true,
  version: 4,
  created_at: "2026-10-11T08:00:00Z",
  updated_at: "2026-10-11T08:00:00Z",
} as unknown as Product;

/** A pretend API: the lookups, who's signed in, and a record of what was sent. */
function stubApi(permissions: string[]) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (input: Request) => {
    const path = new URL(input.url).pathname;
    if (input.method !== "GET") {
      sent.push({ method: input.method, path, body: JSON.parse(await input.clone().text()) });
      return json(200, { ...MILK, version: 5 });
    }
    if (path === "/api/v1/auth/me/") {
      return json(200, { user: { id: "u" }, organization: { base_currency: "KES" }, access: { permissions } });
    }
    if (path === "/api/v1/units/") return json(200, page([{ id: "u1", code: "PCS", name: "Pieces", is_active: true }]));
    if (path === "/api/v1/tax-rates/") {
      // The product's own rate was deactivated since; it must still show by name.
      return json(200, page([
        { id: "t-vat", name: "VAT 16%", rate: "0.1600", is_active: true },
        { id: "t-exempt", name: "Exempt", rate: "0.0000", is_active: false },
        { id: "t-old", name: "Old rate", rate: "0.1400", is_active: false },
      ]));
    }
    return json(200, page([]));
  });
  return sent;
}

function renderForm(product: Product | null, onDone = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProductForm product={product} onDone={onDone} />
    </QueryClientProvider>,
  );
  return onDone;
}

beforeEach(() => {
  document.cookie = "csrftoken=t";
});
afterEach(() => vi.unstubAllGlobals());

describe("ProductForm", () => {
  it("sends only what changed, with the version it was opened at", async () => {
    const sent = stubApi(["products.manage", "products.change_price"]);
    const onDone = renderForm(MILK);

    await screen.findByRole("option", { name: "Exempt (0%)" });
    await userEvent.clear(screen.getByLabelText(/^Name/));
    await userEvent.type(screen.getByLabelText(/^Name/), "Milk 0.5L");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(sent).toEqual([{ method: "PATCH", path: `/api/v1/products/${MILK.id}/`, body: { name: "Milk 0.5L", version: 4 } }]);
  });

  it("keeps a deactivated tax rate the product uses, and offers no other inactive ones", async () => {
    stubApi(["products.manage"]);
    renderForm(MILK);

    expect(await screen.findByRole("option", { name: "Exempt (0%)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Old rate/ })).not.toBeInTheDocument();
  });

  it("locks the price for people who can't change prices", async () => {
    stubApi(["products.manage"]);
    renderForm(MILK);

    const price = await screen.findByLabelText(/^Selling price/);
    await vi.waitFor(() => expect(price).toBeDisabled());
    expect(screen.getByText("You can't change prices. Ask a manager.")).toBeInTheDocument();
  });

  it("creates a product with its first barcode", async () => {
    const sent = stubApi(["products.manage"]);
    const onDone = renderForm(null);

    await screen.findByRole("option", { name: "Pieces (PCS)" });
    await userEvent.type(screen.getByLabelText(/^Name/), "Sugar 1kg");
    await userEvent.type(screen.getByLabelText(/^Selling price/), "150");
    await userEvent.selectOptions(screen.getByLabelText(/^Unit/), "u1");
    await userEvent.selectOptions(screen.getByLabelText(/^Tax rate/), "t-vat");
    await userEvent.type(screen.getByLabelText(/^Barcode/), " 5901234123457 ");
    await userEvent.click(screen.getByRole("button", { name: "Add product" }));

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(sent[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/products/",
      body: { name: "Sugar 1kg", selling_price: "150.00", unit: "u1", tax_rate: "t-vat", category: null, identifiers: [{ value: "5901234123457" }] },
    });
  });
});

describe("percentToFraction", () => {
  it.each([
    ["16", "0.1600"],
    ["8", "0.0800"],
    ["7.5", "0.0750"],
    ["0", "0.0000"],
    ["12.25", "0.1225"],
  ])("turns %s%% into %s exactly", (percent, fraction) => {
    expect(percentToFraction(percent)).toBe(fraction);
  });

  it("passes anything else through for the server to explain", () => {
    expect(percentToFraction("100")).toBe("100");
    expect(percentToFraction("abc")).toBe("abc");
  });
});
