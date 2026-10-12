"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { AmountField, SelectField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { StockRow } from "@/lib/api/types";
import { toScaled } from "@/lib/cart";
import { INVENTORY_KEY } from "@/lib/query-keys";
import { plainQuantity } from "@/lib/sales";

export const REASONS = {
  COUNT_CORRECTION: { label: "Stock count", ask: "How many did you count?", kind: "count" },
  OPENING_BALANCE: { label: "Opening stock", ask: "How many do you have?", kind: "opening" },
  DAMAGED: { label: "Damaged", ask: "How many are damaged?", kind: "remove" },
  EXPIRED: { label: "Expired", ask: "How many have expired?", kind: "remove" },
  THEFT_LOSS: { label: "Theft or loss", ask: "How many are missing?", kind: "remove" },
  FOUND: { label: "Found", ask: "How many did you find?", kind: "add" },
  OTHER: { label: "Other", ask: "Change (use − to remove)", kind: "signed" },
} as const;
export type Reason = keyof typeof REASONS;

/** Count, write off or add stock for one product in one store. */
export function AdjustForm({ storeId, row, currency, onDone }: { storeId: string; row: StockRow; currency: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState<Reason>(Number(row.quantity_on_hand) === 0 ? "OPENING_BALANCE" : "COUNT_CORRECTION");
  const [quantity, setQuantity] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [note, setNote] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  // One key and transaction id per form: a double tap or retry records the adjustment once.
  const [ids] = useState(() => ({ key: newIdempotencyKey(), txn: crypto.randomUUID() }));
  const kind = REASONS[reason].kind;

  const save = useMutation({
    mutationFn: async () => {
      if (kind === "opening") {
        return unwrap(
          api.POST("/api/v1/stores/{store_id}/inventory/opening-balance/", {
            params: { path: { store_id: storeId }, header: { "Idempotency-Key": ids.key } },
            body: { client_txn_id: ids.txn, lines: [{ product_id: row.product_id, quantity, ...(unitCost ? { unit_cost: unitCost } : {}) }] },
          }),
        );
      }
      const line =
        kind === "count"
          ? { product_id: row.product_id, counted_quantity: quantity }
          : { product_id: row.product_id, quantity_delta: kind === "remove" ? `-${quantity}` : quantity };
      return unwrap(
        api.POST("/api/v1/stores/{store_id}/inventory/adjustments/", {
          params: { path: { store_id: storeId }, header: { "Idempotency-Key": ids.key } },
          body: { client_txn_id: ids.txn, reason_code: reason as Exclude<Reason, "OPENING_BALANCE">, note, lines: [line] },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INVENTORY_KEY });
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const signed = kind === "signed" ? quantity.replace(/^-/, "") : quantity;
    if (toScaled(signed, 3) === null) {
      setLocalError("Enter a number, up to 3 decimals.");
      return;
    }
    if (!row.unit.allows_fraction && !/^-?\d+$/.test(quantity.trim())) {
      setLocalError(`${row.name} is counted in whole ${row.unit.name.toLowerCase()}.`);
      return;
    }
    setLocalError(null);
    save.mutate();
  }

  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <p className="text-sm text-slate-700">
        In stock now: <strong className="tabular">{plainQuantity(row.quantity_on_hand)}</strong> {row.unit.name.toLowerCase()}
      </p>
      <SelectField label="Reason" value={reason} onChange={(e) => setReason(e.target.value as Reason)}>
        {Object.entries(REASONS).map(([value, { label }]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </SelectField>
      <TextField
        label={REASONS[reason].ask}
        required
        inputMode={kind === "signed" ? "text" : "decimal"}
        value={quantity}
        onChange={(e) => setQuantity(e.target.value.trim())}
        error={localError ?? errors.lines}
        className="tabular"
        autoFocus
      />
      {kind === "opening" && (
        <AmountField label="Cost per unit" currency={currency} value={unitCost} onValueChange={setUnitCost} hint="What you paid, for profit reports. Optional." />
      )}
      {kind !== "opening" && (
        <TextField label="Note" required={reason === "OTHER"} value={note} onChange={(e) => setNote(e.target.value)} error={errors.note} maxLength={500} />
      )}
      {save.error && !errors.lines && !errors.note ? <ErrorAlert error={save.error} title="Couldn't save the change" /> : null}
      <Button type="submit" loading={save.isPending}>
        Save
      </Button>
    </form>
  );
}
