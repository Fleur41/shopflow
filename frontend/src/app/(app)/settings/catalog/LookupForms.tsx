"use client";

import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CheckboxField, SelectField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import type { Brand, Category, TaxRate, Unit } from "@/lib/api/types";
import { TAX_TYPE_LABELS, formatRate } from "@/lib/catalog";
import { useCategories } from "@/lib/catalog-queries";
import { BRANDS_KEY, CATEGORIES_KEY, TAX_RATES_KEY, UNITS_KEY } from "@/lib/query-keys";

type TaxType = components["schemas"]["EtimsTaxTypeEnum"];
type QuantityUnit = components["schemas"]["EtimsQuantityUnitEnum"];

const QUANTITY_UNITS: { code: QuantityUnit; label: string }[] = [
  { code: "U", label: "U · Pieces / items" },
  { code: "KG", label: "KG · Kilogram" },
  { code: "GRM", label: "GRM · Gram" },
  { code: "LTR", label: "LTR · Litre" },
  { code: "MTR", label: "MTR · Metre" },
  { code: "BX", label: "BX · Box" },
  { code: "DZ", label: "DZ · Dozen" },
  { code: "PA", label: "PA · Packet" },
  { code: "PR", label: "PR · Pair" },
  { code: "SET", label: "SET · Set" },
  { code: "BG", label: "BG · Bag" },
  { code: "CA", label: "CA · Can" },
];

type FormProps<T> = { entry: T | null; onDone: () => void };

/** Save (create or versioned update), refresh the lists, report field errors. */
function useSave(queryKey: QueryKey, save: (idempotencyKey: string) => Promise<unknown>, onDone: () => void) {
  const queryClient = useQueryClient();
  // One key per form: a double-click or retry can never create two entries.
  const [idempotencyKey] = useState(newIdempotencyKey);
  const mutation = useMutation({
    mutationFn: () => save(idempotencyKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey });
      onDone();
    },
  });
  const errors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};
  const stale = mutation.error instanceof ApiError && mutation.error.code === "STALE_VERSION";
  return { mutation, errors, stale };
}

function FormShell({
  save,
  submitLabel,
  onDone,
  children,
}: {
  save: ReturnType<typeof useSave>;
  submitLabel: string;
  onDone: () => void;
  children: ReactNode;
}) {
  const { mutation, errors, stale } = save;
  function onSubmit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {mutation.error && !Object.keys(errors).length && (
        <ErrorAlert error={mutation.error} title={stale ? "Someone else changed this" : undefined} />
      )}
      {children}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={mutation.isPending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

function ActiveField({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <CheckboxField
      label="Active"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      hint="Inactive entries can't be chosen for products. Nothing is deleted."
    />
  );
}

// --- Categories ---------------------------------------------------------------------

export function CategoryForm({ entry, onDone }: FormProps<Category>) {
  const categories = useCategories(true);
  const [form, setForm] = useState({ name: entry?.name ?? "", parent: entry?.parent ?? "", is_active: entry?.is_active ?? true });
  const body = { name: form.name, parent: form.parent || null, is_active: form.is_active };
  const save = useSave(
    CATEGORIES_KEY,
    (key) =>
      entry
        ? unwrap(api.PATCH("/api/v1/categories/{entry_id}/", { params: { path: { entry_id: entry.id } }, body: { ...body, version: entry.version } }))
        : unwrap(api.POST("/api/v1/categories/", { body, params: { header: { "Idempotency-Key": key } } })),
    onDone,
  );
  const parents = (categories.data?.results ?? []).filter((c) => c.id !== entry?.id);
  return (
    <FormShell save={save} submitLabel={entry ? "Save changes" : "Add category"} onDone={onDone}>
      <TextField label="Name" required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={save.errors.name} />
      <SelectField label="Inside" value={form.parent} onChange={(e) => setForm({ ...form, parent: e.target.value })} error={save.errors.parent} hint="Leave as top level, or put it inside another category.">
        <option value="">Top level</option>
        {parents.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </SelectField>
      {entry && <ActiveField checked={form.is_active} onChange={(is_active) => setForm({ ...form, is_active })} />}
    </FormShell>
  );
}

// --- Brands -------------------------------------------------------------------------

export function BrandForm({ entry, onDone }: FormProps<Brand>) {
  const [form, setForm] = useState({ name: entry?.name ?? "", is_active: entry?.is_active ?? true });
  const save = useSave(
    BRANDS_KEY,
    (key) =>
      entry
        ? unwrap(api.PATCH("/api/v1/brands/{entry_id}/", { params: { path: { entry_id: entry.id } }, body: { ...form, version: entry.version } }))
        : unwrap(api.POST("/api/v1/brands/", { body: form, params: { header: { "Idempotency-Key": key } } })),
    onDone,
  );
  return (
    <FormShell save={save} submitLabel={entry ? "Save changes" : "Add brand"} onDone={onDone}>
      <TextField label="Name" required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={save.errors.name} />
      {entry && <ActiveField checked={form.is_active} onChange={(is_active) => setForm({ ...form, is_active })} />}
    </FormShell>
  );
}

// --- Units ----------------------------------------------------------------------------

export function UnitForm({ entry, onDone }: FormProps<Unit>) {
  const [form, setForm] = useState({
    code: entry?.code ?? "",
    name: entry?.name ?? "",
    allows_fraction: entry?.allows_fraction ?? false,
    etims_quantity_unit: (entry?.etims_quantity_unit ?? "") as QuantityUnit | "",
    is_active: entry?.is_active ?? true,
  });
  const save = useSave(
    UNITS_KEY,
    (key) =>
      entry
        ? unwrap(api.PATCH("/api/v1/units/{entry_id}/", { params: { path: { entry_id: entry.id } }, body: { ...form, version: entry.version } }))
        : unwrap(api.POST("/api/v1/units/", { body: form, params: { header: { "Idempotency-Key": key } } })),
    onDone,
  );
  return (
    <FormShell save={save} submitLabel={entry ? "Save changes" : "Add unit"} onDone={onDone}>
      <TextField label="Code" required maxLength={10} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} error={save.errors.code} hint="Short, e.g. PCS or KG." />
      <TextField label="Name" required maxLength={40} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={save.errors.name} />
      <CheckboxField
        label="Sold in fractions"
        checked={form.allows_fraction}
        onChange={(e) => setForm({ ...form, allows_fraction: e.target.checked })}
        hint="For quantities like 0.5 kg or 1.25 m."
      />
      <SelectField
        label="KRA eTIMS unit"
        value={form.etims_quantity_unit}
        onChange={(e) => setForm({ ...form, etims_quantity_unit: e.target.value as QuantityUnit | "" })}
        error={save.errors.etims_quantity_unit}
        hint="Needed once eTIMS is switched on."
      >
        <option value="">Not set</option>
        {QUANTITY_UNITS.map((u) => (
          <option key={u.code} value={u.code}>
            {u.label}
          </option>
        ))}
        {form.etims_quantity_unit && !QUANTITY_UNITS.some((u) => u.code === form.etims_quantity_unit) && (
          <option value={form.etims_quantity_unit}>{form.etims_quantity_unit}</option>
        )}
      </SelectField>
      {entry && <ActiveField checked={form.is_active} onChange={(is_active) => setForm({ ...form, is_active })} />}
    </FormShell>
  );
}

// --- Tax rates ------------------------------------------------------------------------

export function TaxRateForm({ entry, onDone }: FormProps<TaxRate>) {
  const [form, setForm] = useState({
    name: entry?.name ?? "",
    // Shown as a percentage; the API takes a fraction (16 → "0.16").
    percent: entry ? String(Number((Number(entry.rate) * 100).toFixed(2))) : "",
    etims_tax_type: (entry?.etims_tax_type ?? "") as TaxType | "",
    is_active: entry?.is_active ?? true,
  });
  const save = useSave(
    TAX_RATES_KEY,
    (key) => {
      const common = { name: form.name, etims_tax_type: form.etims_tax_type, is_active: form.is_active };
      return entry
        ? unwrap(api.PATCH("/api/v1/tax-rates/{entry_id}/", { params: { path: { entry_id: entry.id } }, body: { ...common, version: entry.version } }))
        : unwrap(
            api.POST("/api/v1/tax-rates/", {
              body: { ...common, rate: percentToFraction(form.percent) },
              params: { header: { "Idempotency-Key": key } },
            }),
          );
    },
    onDone,
  );
  return (
    <FormShell save={save} submitLabel={entry ? "Save changes" : "Add tax rate"} onDone={onDone}>
      <TextField label="Name" required maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={save.errors.name} />
      {entry ? (
        <p className="text-sm text-slate-600">
          Rate {formatRate(entry.rate)}. A rate can’t change once created: add a new one and move products to it.
        </p>
      ) : (
        <TextField
          label="Rate (%)"
          required
          inputMode="decimal"
          value={form.percent}
          onChange={(e) => setForm({ ...form, percent: e.target.value })}
          error={save.errors.rate}
          hint="For example 16 for 16% VAT. Can’t be changed later."
        />
      )}
      <SelectField
        label="KRA eTIMS tax type"
        value={form.etims_tax_type}
        onChange={(e) => setForm({ ...form, etims_tax_type: e.target.value as TaxType | "" })}
        error={save.errors.etims_tax_type}
        hint="Needed once eTIMS is switched on."
      >
        <option value="">Not set</option>
        {(Object.keys(TAX_TYPE_LABELS) as TaxType[]).map((code) => (
          <option key={code} value={code}>
            {TAX_TYPE_LABELS[code]}
          </option>
        ))}
      </SelectField>
      {entry && <ActiveField checked={form.is_active} onChange={(is_active) => setForm({ ...form, is_active })} />}
    </FormShell>
  );
}

/** "16" → "0.16", "7.5" → "0.075", exactly (string arithmetic, no floats). */
export function percentToFraction(percent: string): string {
  const match = /^\s*(\d{1,2})(?:\.(\d{1,2}))?\s*$/.exec(percent);
  if (!match) return percent.trim(); // let the server explain what's wrong
  const [, whole = "0", fraction = ""] = match;
  const digits = (whole.padStart(2, "0") + fraction.padEnd(2, "0")).replace(/^0+(?=\d)/, "");
  return `0.${digits.padStart(4, "0")}`;
}
