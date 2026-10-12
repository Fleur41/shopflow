"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { AmountField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Customer } from "@/lib/api/types";
import { CUSTOMERS_KEY } from "@/lib/query-keys";

type Fields = { name: string; phone: string; email: string; address: string; notes: string };

function fieldsOf(customer: Customer | null): Fields {
  return {
    name: customer?.name ?? "",
    phone: customer?.phone ?? "",
    email: customer?.email ?? "",
    address: customer?.address ?? "",
    notes: customer?.notes ?? "",
  };
}

/** Add a customer (optionally with a credit limit), or edit their details. */
export function CustomerForm({
  customer,
  currency,
  canSetLimit,
  onDone,
}: {
  customer: Customer | null;
  currency: string;
  canSetLimit: boolean;
  onDone: (saved: Customer) => void;
}) {
  const queryClient = useQueryClient();
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [form, setForm] = useState<Fields>(() => fieldsOf(customer));
  const [limit, setLimit] = useState("");
  const set = (name: keyof Fields) => (value: string) => setForm((current) => ({ ...current, [name]: value }));

  const save = useMutation({
    mutationFn: () => {
      if (!customer) {
        return unwrap(
          api.POST("/api/v1/customers/", {
            body: { ...form, ...(limit ? { credit_limit: limit } : {}) },
            params: { header: { "Idempotency-Key": idempotencyKey } },
          }),
        );
      }
      const original = fieldsOf(customer);
      const changes = Object.fromEntries(Object.entries(form).filter(([key, value]) => original[key as keyof Fields] !== value));
      return unwrap(api.PATCH("/api/v1/customers/{entry_id}/", { params: { path: { entry_id: customer.id } }, body: { ...changes, version: customer.version } }));
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      onDone(saved);
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <TextField label="Name" required value={form.name} onChange={(e) => set("name")(e.target.value)} error={errors.name} autoFocus={!customer} />
      <TextField label="Phone" type="tel" inputMode="tel" value={form.phone} onChange={(e) => set("phone")(e.target.value)} error={errors.phone} placeholder="+254 7xx xxx xxx" />
      <TextField label="Email" type="email" value={form.email} onChange={(e) => set("email")(e.target.value)} error={errors.email} />
      <TextField label="Address" value={form.address} onChange={(e) => set("address")(e.target.value)} error={errors.address} />
      <TextField label="Notes" value={form.notes} onChange={(e) => set("notes")(e.target.value)} error={errors.notes} />
      {!customer && canSetLimit && (
        <AmountField label="Credit limit" currency={currency} value={limit} onValueChange={setLimit} error={errors.credit_limit} hint="How much they may owe. Empty: cash only." />
      )}
      {save.error && !Object.keys(errors).length ? <ErrorAlert error={save.error} title="Couldn't save the customer" /> : null}
      <Button type="submit" loading={save.isPending}>
        {customer ? "Save changes" : "Add customer"}
      </Button>
    </form>
  );
}
