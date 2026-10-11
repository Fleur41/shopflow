"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Supplier } from "@/lib/api/types";
import { SUPPLIERS_KEY } from "@/lib/query-keys";

type Fields = {
  name: string;
  code: string;
  kra_pin: string;
  phone: string;
  email: string;
  address: string;
  payment_terms_days: string;
  notes: string;
};

function fieldsOf(supplier: Supplier | null): Fields {
  return {
    name: supplier?.name ?? "",
    code: supplier?.code ?? "",
    kra_pin: supplier?.kra_pin ?? "",
    phone: supplier?.phone ?? "",
    email: supplier?.email ?? "",
    address: supplier?.address ?? "",
    payment_terms_days: String(supplier?.payment_terms_days ?? 0),
    notes: supplier?.notes ?? "",
  };
}

/** Create a supplier, or edit one (sending only what changed, with its version). */
export function SupplierForm({ supplier, onDone }: { supplier: Supplier | null; onDone: (saved: Supplier) => void }) {
  const queryClient = useQueryClient();
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [form, setForm] = useState<Fields>(() => fieldsOf(supplier));

  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, payment_terms_days: Number(form.payment_terms_days || 0) };
      if (!supplier) {
        return unwrap(api.POST("/api/v1/suppliers/", { body, params: { header: { "Idempotency-Key": idempotencyKey } } }));
      }
      const original = { ...fieldsOf(supplier), payment_terms_days: supplier.payment_terms_days ?? 0 };
      const changes = Object.fromEntries(
        Object.entries(body).filter(([key, value]) => key !== "code" && original[key as keyof typeof original] !== value),
      );
      return unwrap(
        api.PATCH("/api/v1/suppliers/{entry_id}/", {
          params: { path: { entry_id: supplier.id } },
          body: { ...changes, version: supplier.version },
        }),
      );
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: SUPPLIERS_KEY });
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

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {save.error && !Object.keys(errors).length && <ErrorAlert error={save.error} title={stale ? "Someone else changed this supplier" : undefined} />}
      <TextField label="Name" required maxLength={120} value={form.name} onChange={set("name")} error={errors.name} />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Phone" type="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} error={errors.phone} />
        <TextField label="Email" type="email" autoComplete="email" value={form.email} onChange={set("email")} error={errors.email} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="KRA PIN"
          value={form.kra_pin}
          onChange={set("kra_pin")}
          error={errors.kra_pin}
          maxLength={11}
          hint="e.g. P051234567X. Matches their eTIMS invoices to them."
          className="uppercase"
        />
        <TextField
          label="Payment terms (days)"
          inputMode="numeric"
          value={form.payment_terms_days}
          onChange={set("payment_terms_days")}
          error={errors.payment_terms_days}
          hint="0 means you pay on delivery."
        />
      </div>
      <TextField label="Address" maxLength={300} value={form.address} onChange={set("address")} error={errors.address} />
      {!supplier && (
        <TextField label="Code" maxLength={20} value={form.code} onChange={set("code")} error={errors.code} hint="Leave empty to get one (S00001, …)." />
      )}
      <TextField label="Notes" maxLength={2000} value={form.notes} onChange={set("notes")} error={errors.notes} hint="Delivery days, account numbers, anything useful." />
      <div className="flex justify-end">
        <Button type="submit" loading={save.isPending}>
          {supplier ? "Save changes" : "Add supplier"}
        </Button>
      </div>
    </form>
  );
}

/** "On delivery", "7 days", "30 days". */
export function paymentTerms(days: number | undefined): string {
  if (!days) return "On delivery";
  return `${days} day${days === 1 ? "" : "s"}`;
}
