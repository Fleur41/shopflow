"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CheckboxField, SelectField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { EtimsPaymentType, PaymentMethod, PaymentMethodKind } from "@/lib/api/types";
import { ETIMS_LABELS, KIND_LABELS, usuallyNeedsReference } from "@/lib/payment-methods";
import { PAYMENT_METHODS_KEY } from "@/lib/query-keys";

const KINDS = Object.keys(KIND_LABELS) as PaymentMethodKind[];
const ETIMS_TYPES = Object.keys(ETIMS_LABELS) as EtimsPaymentType[];

function useInvalidateAndClose(onDone: () => void) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: PAYMENT_METHODS_KEY });
    onDone();
  };
}

export function AddPaymentMethodForm({ onDone }: { onDone: () => void }) {
  // One key per form: a double-click or retry can never create two methods.
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [form, setForm] = useState({
    code: "",
    name: "",
    kind: "MOBILE_MONEY" as PaymentMethodKind,
    requires_reference: true,
    etims_payment_type: "" as EtimsPaymentType | "",
  });
  const create = useMutation({
    mutationFn: () => {
      const { etims_payment_type, ...rest } = form;
      // Left empty, the server picks the eTIMS type that matches the kind.
      const body = etims_payment_type ? { ...rest, etims_payment_type } : rest;
      return unwrap(
        api.POST("/api/v1/payment-methods/", {
          body,
          params: { header: { "Idempotency-Key": idempotencyKey } },
        }),
      );
    },
    onSuccess: useInvalidateAndClose(onDone),
  });
  const errors = create.error instanceof ApiError ? create.error.fieldErrors() : {};

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {create.error && !Object.keys(errors).length && <ErrorAlert error={create.error} />}
      <TextField label="Name" required maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} hint="Shown on the till button and receipts, e.g. Airtel Money." />
      <TextField
        label="Code"
        required
        maxLength={20}
        value={form.code}
        onChange={(e) => setForm({ ...form, code: e.target.value })}
        error={errors.code}
        hint="2–20 letters, digits or underscores, e.g. AIRTEL. Used in reports; can’t be changed later."
      />
      <SelectField
        label="Kind"
        value={form.kind}
        onChange={(e) => {
          const kind = e.target.value as PaymentMethodKind;
          setForm({ ...form, kind, requires_reference: usuallyNeedsReference(kind) });
        }}
        error={errors.kind}
        hint="Cash gives change and counts towards the till. Can’t be changed later."
      >
        {KINDS.map((kind) => (
          <option key={kind} value={kind}>
            {KIND_LABELS[kind]}
          </option>
        ))}
      </SelectField>
      <CheckboxField
        label="Cashier must enter a reference"
        checked={form.requires_reference}
        onChange={(e) => setForm({ ...form, requires_reference: e.target.checked })}
        hint="For example the M-Pesa transaction code, so payments can be checked later."
      />
      <SelectField
        label="KRA eTIMS payment type"
        value={form.etims_payment_type}
        onChange={(e) => setForm({ ...form, etims_payment_type: e.target.value as EtimsPaymentType | "" })}
        error={errors.etims_payment_type}
      >
        <option value="">Automatic (matches the kind)</option>
        {ETIMS_TYPES.map((type) => (
          <option key={type} value={type}>
            {ETIMS_LABELS[type]}
          </option>
        ))}
      </SelectField>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={create.isPending}>
          Add payment method
        </Button>
      </div>
    </form>
  );
}

export function EditPaymentMethodForm({ method, onDone }: { method: PaymentMethod; onDone: () => void }) {
  const [form, setForm] = useState({
    name: method.name,
    position: String(method.position ?? 0),
    requires_reference: method.requires_reference ?? false,
    etims_payment_type: method.etims_payment_type ?? "07",
    is_active: method.is_active ?? true,
  });
  const update = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/payment-methods/{entry_id}/", {
          params: { path: { entry_id: method.id } },
          body: { ...form, position: Number(form.position), version: method.version },
        }),
      ),
    onSuccess: useInvalidateAndClose(onDone),
  });
  const errors = update.error instanceof ApiError ? update.error.fieldErrors() : {};
  const stale = update.error instanceof ApiError && update.error.code === "STALE_VERSION";

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {update.error && !Object.keys(errors).length && (
        <ErrorAlert error={update.error} title={stale ? "Someone else changed this payment method" : undefined} />
      )}
      <p className="text-sm text-slate-600">
        Code <span className="font-mono">{method.code}</span> · {KIND_LABELS[method.kind]}
      </p>
      <TextField label="Name" required maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} />
      <TextField
        label="Position"
        type="number"
        inputMode="numeric"
        min={0}
        value={form.position}
        onChange={(e) => setForm({ ...form, position: e.target.value })}
        error={errors.position}
        hint="Lower numbers come first at the till."
      />
      <CheckboxField label="Cashier must enter a reference" checked={form.requires_reference} onChange={(e) => setForm({ ...form, requires_reference: e.target.checked })} />
      <SelectField
        label="KRA eTIMS payment type"
        value={form.etims_payment_type}
        onChange={(e) => setForm({ ...form, etims_payment_type: e.target.value as EtimsPaymentType })}
        error={errors.etims_payment_type}
      >
        {ETIMS_TYPES.map((type) => (
          <option key={type} value={type}>
            {ETIMS_LABELS[type]}
          </option>
        ))}
      </SelectField>
      <CheckboxField
        label="Active"
        checked={form.is_active}
        onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
        hint="Inactive methods disappear from the till. Past payments keep it."
      />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={update.isPending}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
