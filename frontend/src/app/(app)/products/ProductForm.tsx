"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CheckboxField, SelectField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import type { Product } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { PRODUCT_TYPE_LABELS, formatRate } from "@/lib/catalog";
import { useBrands, useCategories, useTaxRates, useUnits } from "@/lib/catalog-queries";
import { PRODUCTS_KEY } from "@/lib/query-keys";

type ProductType = components["schemas"]["EtimsProductTypeEnum"];

type Fields = {
  name: string;
  sku: string;
  category: string;
  brand: string;
  unit: string;
  tax_rate: string;
  selling_price: string;
  default_cost: string;
  track_inventory: boolean;
  etims_product_type: ProductType;
  etims_item_class_code: string;
};

function fieldsOf(product: Product | null): Fields {
  return {
    name: product?.name ?? "",
    sku: product?.sku ?? "",
    category: product?.category ?? "",
    brand: product?.brand ?? "",
    unit: product?.unit ?? "",
    tax_rate: product?.tax_rate ?? "",
    selling_price: product ? trimZeros(product.selling_price) : "",
    default_cost: product?.default_cost ? trimZeros(product.default_cost) : "",
    track_inventory: product?.track_inventory ?? true,
    etims_product_type: product?.etims_product_type ?? "2",
    etims_item_class_code: product?.etims_item_class_code ?? "",
  };
}

/** "60.0000" → "60.00": the API stores 4 places, people type 2. */
function trimZeros(amount: string): string {
  return amount.replace(/(\.\d\d)0+$/, "$1");
}

/** What the API takes, with empty optional choices as null. */
function toBody(fields: Fields) {
  return {
    ...fields,
    category: fields.category || null,
    brand: fields.brand || null,
    default_cost: fields.default_cost || null,
  };
}

/** Only what changed, so an unchanged price never needs the price permission. */
function changesOf(before: Fields, after: Fields): Partial<ReturnType<typeof toBody>> {
  const body = toBody(after);
  const original = toBody(before);
  return Object.fromEntries(
    Object.entries(body).filter(([key, value]) => original[key as keyof typeof original] !== value),
  ) as Partial<typeof body>;
}

/**
 * Create a product (with an optional first barcode), or edit one.
 */
export function ProductForm({ product, onDone }: { product: Product | null; onDone: (saved: Product) => void }) {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [form, setForm] = useState<Fields>(() => fieldsOf(product));
  const [barcode, setBarcode] = useState("");
  // Full lists (they're short): active entries plus the product's own, if inactive.
  const categories = useCategories();
  const brands = useBrands();
  const units = useUnits();
  const taxRates = useTaxRates();
  const canChangePrice = !product || can(me, "products.change_price");

  const save = useMutation({
    mutationFn: () =>
      product
        ? unwrap(
            api.PATCH("/api/v1/products/{entry_id}/", {
              params: { path: { entry_id: product.id } },
              body: { ...changesOf(fieldsOf(product), form), version: product.version },
            }),
          )
        : unwrap(
            api.POST("/api/v1/products/", {
              body: { ...toBody(form), identifiers: barcode.trim() ? [{ value: barcode.trim() }] : [] },
              params: { header: { "Idempotency-Key": idempotencyKey } },
            }),
          ),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: PRODUCTS_KEY });
      onDone(saved);
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  const stale = save.error instanceof ApiError && save.error.code === "STALE_VERSION";
  const set = (field: keyof Fields) => (e: { target: { value: string } }) => setForm((current) => ({ ...current, [field]: e.target.value }));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const isService = form.etims_product_type === "3";

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {save.error && !Object.keys(errors).filter((f) => f !== "identifiers").length && (
        <ErrorAlert error={save.error} title={stale ? "Someone else changed this product" : undefined} />
      )}
      <TextField label="Name" required maxLength={200} value={form.name} onChange={set("name")} error={errors.name} />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Selling price"
          required
          inputMode="decimal"
          value={form.selling_price}
          onChange={set("selling_price")}
          error={errors.selling_price}
          disabled={!canChangePrice}
          hint={canChangePrice ? undefined : "You can't change prices. Ask a manager."}
        />
        <TextField label="Cost (optional)" inputMode="decimal" value={form.default_cost} onChange={set("default_cost")} error={errors.default_cost} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Unit" required value={form.unit} onChange={set("unit")} error={errors.unit}>
          <option value="">Choose…</option>
          {choices(units.data?.results, product?.unit).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name} ({u.code})
            </option>
          ))}
        </SelectField>
        <SelectField label="Tax rate" required value={form.tax_rate} onChange={set("tax_rate")} error={errors.tax_rate}>
          <option value="">Choose…</option>
          {choices(taxRates.data?.results, product?.tax_rate).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({formatRate(t.rate)})
            </option>
          ))}
        </SelectField>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Category" value={form.category} onChange={set("category")} error={errors.category}>
          <option value="">None</option>
          {choices(categories.data?.results, product?.category).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </SelectField>
        <SelectField label="Brand" value={form.brand} onChange={set("brand")} error={errors.brand}>
          <option value="">None</option>
          {choices(brands.data?.results, product?.brand).map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </SelectField>
      </div>
      <TextField label="SKU" maxLength={40} value={form.sku} onChange={set("sku")} error={errors.sku} hint={product ? undefined : "Your own code. Leave empty to get one (P000001, …)."} />
      {!product && (
        <TextField
          label="Barcode (optional)"
          inputMode="numeric"
          value={barcode}
          onChange={(e) => setBarcode(e.target.value)}
          error={errors.identifiers}
          hint="Scan it or type it. You can add more codes later."
        />
      )}
      <SelectField
        label="Kind"
        value={form.etims_product_type}
        onChange={(e) => {
          const type = e.target.value as ProductType;
          setForm({ ...form, etims_product_type: type, track_inventory: type !== "3" && form.track_inventory });
        }}
        error={errors.etims_product_type}
      >
        {(Object.keys(PRODUCT_TYPE_LABELS) as ProductType[]).map((type) => (
          <option key={type} value={type}>
            {PRODUCT_TYPE_LABELS[type]}
          </option>
        ))}
      </SelectField>
      <CheckboxField
        label="Track stock"
        checked={form.track_inventory}
        disabled={isService}
        onChange={(e) => setForm({ ...form, track_inventory: e.target.checked })}
        error={errors.track_inventory}
        hint={isService ? "Services don't have stock." : undefined}
      />
      <TextField
        label="KRA item classification (optional)"
        inputMode="numeric"
        maxLength={10}
        value={form.etims_item_class_code}
        onChange={set("etims_item_class_code")}
        error={errors.etims_item_class_code}
        hint="Needed once eTIMS is switched on."
      />
      <div className="flex justify-end gap-2">
        <Button type="submit" loading={save.isPending}>
          {product ? "Save changes" : "Add product"}
        </Button>
      </div>
    </form>
  );
}

/** Active entries, plus the one the product already uses even if deactivated since. */
function choices<T extends { id: string; is_active?: boolean }>(all: T[] | undefined, current: string | null | undefined): T[] {
  return (all ?? []).filter((entry) => entry.is_active || entry.id === current);
}
