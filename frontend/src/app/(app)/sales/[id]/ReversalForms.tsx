"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CheckboxField, SelectField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Sale } from "@/lib/api/types";
import { fromScaled, toScaled } from "@/lib/cart";
import { CASH_KEY, CUSTOMERS_KEY, INVENTORY_KEY, PAYMENT_METHODS_KEY, SALES_KEY } from "@/lib/query-keys";
import { plainQuantity } from "@/lib/sales";

function useInvalidateAfterReversal() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [SALES_KEY, INVENTORY_KEY, CASH_KEY, CUSTOMERS_KEY]) void queryClient.invalidateQueries({ queryKey: key });
  };
}

/** Undo the whole of today's sale: stock, money and credit all go back. */
export function VoidForm({ sale, storeId, onDone }: { sale: Sale; storeId: string; onDone: () => void }) {
  const invalidate = useInvalidateAfterReversal();
  const [key] = useState(newIdempotencyKey);
  const [reason, setReason] = useState("");
  const voiding = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/sales/{sale_id}/void/", {
          params: { path: { store_id: storeId, sale_id: sale.id }, header: { "Idempotency-Key": key } },
          body: { reason },
        }),
      ),
    onSuccess: () => {
      invalidate();
      onDone();
    },
  });
  const errors = voiding.error instanceof ApiError ? voiding.error.fieldErrors() : {};
  const paidBack = sale.payments.filter((payment) => payment.direction === "IN");
  function submit(event: FormEvent) {
    event.preventDefault();
    voiding.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <div className="text-sm text-slate-700">
        <p>All items go back into stock.</p>
        {paidBack.map((payment, index) => (
          <p key={index}>
            Give back <Money amount={payment.amount} currency={sale.currency} size="sm" /> {payment.kind === "CASH" ? "in cash from the till" : `by ${payment.method_name}`}.
          </p>
        ))}
        {Number(sale.amount_on_credit) > 0 && (
          <p>
            <Money amount={sale.amount_on_credit} currency={sale.currency} size="sm" /> comes off {sale.customer?.name}’s account.
          </p>
        )}
      </div>
      <TextField label="Why?" required value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} placeholder="e.g. Rang up twice" autoFocus maxLength={300} />
      {voiding.error && !errors.reason ? <ErrorAlert error={voiding.error} title="Couldn't void the sale" /> : null}
      <Button type="submit" variant="danger" loading={voiding.isPending}>
        Void sale
      </Button>
    </form>
  );
}

/** Take back some or all items; refund in cash/M-Pesa or off the customer's account. */
export function ReturnForm({ sale, storeId, onDone }: { sale: Sale; storeId: string; onDone: () => void }) {
  const invalidate = useInvalidateAfterReversal();
  const [ids] = useState(() => ({ key: newIdempotencyKey(), txn: crypto.randomUUID() }));
  const lines = sale.items.map((item) => ({ item, left: (toScaled(item.quantity, 3) ?? 0n) - (toScaled(item.returned_quantity, 3) ?? 0n) })).filter((line) => line.left > 0n);
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [restock, setRestock] = useState<Record<number, boolean>>({});
  const [refundTo, setRefundTo] = useState("");
  const [reason, setReason] = useState("");
  const methods = useQuery({
    queryKey: [...PAYMENT_METHODS_KEY, "till"],
    queryFn: () => unwrap(api.GET("/api/v1/payment-methods/", { params: { query: { is_active: true, page_size: 50 } } })),
    select: (page) => [...page.results].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)),
  });
  const choice = refundTo || (Number(sale.amount_on_credit) > 0 ? "ACCOUNT" : (methods.data?.[0]?.id ?? ""));
  const chosen = lines.filter((line) => (quantities[line.item.line_no] ?? "").trim() !== "");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/sales/{sale_id}/returns/", {
          params: { path: { store_id: storeId, sale_id: sale.id }, header: { "Idempotency-Key": ids.key } },
          body: {
            client_txn_id: ids.txn,
            reason,
            items: chosen.map(({ item }) => ({ line_no: item.line_no, quantity: quantities[item.line_no] ?? "", restock: restock[item.line_no] ?? true })),
            refund_to: choice === "ACCOUNT" ? "ACCOUNT" : "PAYMENT",
            payment_method_id: choice === "ACCOUNT" ? null : choice,
            cash_session_id: null,
          },
        }),
      ),
    onSuccess: () => {
      invalidate();
      onDone();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-sm font-medium text-slate-800">What came back?</legend>
        {lines.map(({ item, left }) => (
          <div key={item.line_no} className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
            <div className="flex items-end justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium">{item.product_name}</p>
                <p className="text-xs text-slate-600">
                  Up to {plainQuantity(fromScaled(left, 3))} · <Money amount={item.unit_price} currency={sale.currency} size="sm" /> each
                </p>
              </div>
              <div className="w-24 shrink-0">
                <TextField
                  label="Qty"
                  inputMode="decimal"
                  value={quantities[item.line_no] ?? ""}
                  onChange={(e) => setQuantities({ ...quantities, [item.line_no]: e.target.value.trim() })}
                  aria-label={`How many ${item.product_name} came back`}
                  className="tabular text-right"
                />
              </div>
            </div>
            {(quantities[item.line_no] ?? "") !== "" && (
              <CheckboxField
                label="Back on the shelf"
                checked={restock[item.line_no] ?? true}
                onChange={(e) => setRestock({ ...restock, [item.line_no]: e.target.checked })}
                hint="Untick if it's damaged and can't be sold."
              />
            )}
          </div>
        ))}
      </fieldset>
      {errors.items && <p className="text-sm font-medium text-red-700">{errors.items}</p>}
      <SelectField label="Refund" value={choice} onChange={(e) => setRefundTo(e.target.value)}>
        {sale.customer && <option value="ACCOUNT">Off {sale.customer.name}’s account</option>}
        {methods.data?.map((method) => (
          <option key={method.id} value={method.id}>
            {method.kind === "CASH" ? "Cash from the till" : method.name}
          </option>
        ))}
      </SelectField>
      <TextField label="Why?" required value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} placeholder="e.g. Expired when bought" maxLength={300} />
      {save.error && !errors.reason && !errors.items ? <ErrorAlert error={save.error} title="Couldn't process the return" /> : null}
      <Button type="submit" loading={save.isPending} disabled={chosen.length === 0}>
        Process return
      </Button>
    </form>
  );
}
