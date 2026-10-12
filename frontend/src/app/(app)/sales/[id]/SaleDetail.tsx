"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Ban, Printer, Undo2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, Card, ErrorAlert, Loading, Notice } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
import { SALES_KEY } from "@/lib/query-keys";
import { formatDateTime, plainQuantity, useSaleStoreId } from "@/lib/sales";

import { ReturnForm, VoidForm } from "./ReversalForms";

export function SaleDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const storeId = useSaleStoreId(me);
  const sale = useQuery({
    queryKey: [...SALES_KEY, storeId, id],
    enabled: Boolean(storeId),
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/sales/{sale_id}/", { params: { path: { store_id: storeId ?? "", sale_id: id } } })),
  });
  const data = sale.data;
  const [dialog, setDialog] = useState<"void" | "return" | null>(null);
  const timeZone = me?.organization?.timezone;
  const completed = data?.status === "COMPLETED";
  const anythingLeft = data?.items.some((item) => Number(item.returned_quantity) < Number(item.quantity)) ?? false;

  return (
    <>
      <Link href="/sales" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" />
        All sales
      </Link>
      {sale.isPending && <Loading label="Loading sale…" />}
      {sale.error && <ErrorAlert error={sale.error} title="Couldn't load this sale" />}
      {data && (
        <>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-emerald-800">
                {formatDateTime(data.occurred_at, timeZone)} · {data.cashier.name}
              </p>
              <h1 className="tabular font-mono text-2xl font-semibold tracking-tight">{data.receipt_number}</h1>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge tone={data.status === "COMPLETED" ? "success" : "neutral"}>{data.status === "COMPLETED" ? "Completed" : "Voided"}</Badge>
                {data.customer && <Badge>{data.customer.name}</Badge>}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {completed && anythingLeft && can(me, "sales.return") && (
                <Button variant="secondary" onClick={() => setDialog("return")}>
                  <Undo2 aria-hidden="true" className="size-4" /> Return items
                </Button>
              )}
              {completed && data.returns.length === 0 && can(me, "sales.void") && (
                <Button variant="secondary" className="text-red-800" onClick={() => setDialog("void")}>
                  <Ban aria-hidden="true" className="size-4" /> Void
                </Button>
              )}
              <Link
                href={`/sales/${data.id}/receipt?store=${storeId}&reprint=1`}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
              >
                <Printer aria-hidden="true" className="size-4" /> Reprint receipt
              </Link>
            </div>
          </div>
          {data.status === "VOIDED" && (
            <Notice>
              <p className="font-semibold">Voided</p>
              <p className="mt-1">
                {data.voided_at && formatDateTime(data.voided_at, timeZone)}
                {data.voided_by && ` by ${data.voided_by.name}`}: {data.void_reason}. Stock, money and credit were all put back.
              </p>
            </Notice>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="table-card">
              <table>
                <caption className="sr-only">Items</caption>
                <thead>
                  <tr>
                    <th scope="col">Item</th>
                    <th scope="col" className="num">
                      Qty
                    </th>
                    <th scope="col" className="num">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.line_no}>
                      <td>
                        <Link href={`/products/${item.product_id}`} className="font-medium hover:text-emerald-800 hover:underline">
                          {item.product_name}
                        </Link>
                        <p className="text-xs text-slate-600">
                          <Money amount={item.unit_price} currency={data.currency} size="sm" /> each · {item.tax_name}
                          {item.price_overridden && ` · price changed: ${item.override_reason}`}
                        </p>
                      </td>
                      <td className="num tabular">
                        {plainQuantity(item.quantity)} {item.unit_code !== "PCS" && item.unit_code.toLowerCase()}
                        {Number(item.returned_quantity) > 0 && <span className="block text-xs text-amber-800">{plainQuantity(item.returned_quantity)} returned</span>}
                      </td>
                      <td className="num">
                        <Money amount={item.line_total} currency={data.currency} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-6">
              <Card title="Totals">
                <dl className="flex flex-col gap-2 text-sm">
                  {Number(data.discount_total) > 0 && <Row label="Discounts" amount={`-${data.discount_total}`} currency={data.currency} />}
                  <Row label={data.tax_mode === "INCLUSIVE" ? "Tax included" : "Tax"} amount={data.tax_total} currency={data.currency} />
                  <div className="flex items-baseline justify-between border-t border-slate-100 pt-2">
                    <dt className="font-semibold">Total</dt>
                    <dd>
                      <Money amount={data.total} currency={data.currency} size="lg" />
                    </dd>
                  </div>
                </dl>
              </Card>
              <Card title="Payment">
                <dl className="flex flex-col gap-2 text-sm">
                  {data.payments.map((payment, index) => (
                    <Row
                      key={index}
                      label={`${payment.direction === "OUT" ? "Refunded · " : ""}${payment.method_name}${payment.reference ? ` · ${payment.reference}` : ""}`}
                      amount={payment.direction === "OUT" ? `-${payment.amount}` : payment.amount}
                      currency={data.currency}
                    />
                  ))}
                  {Number(data.amount_on_credit) > 0 && <Row label={`On ${data.customer?.name ?? "account"}`} amount={data.amount_on_credit} currency={data.currency} />}
                  {Number(data.change_given) > 0 && <Row label="Change given" amount={data.change_given} currency={data.currency} />}
                </dl>
              </Card>
              {data.returns.length > 0 && (
                <Card title="Returns">
                  <ul className="flex flex-col divide-y divide-slate-100 text-sm">
                    {data.returns.map((r) => (
                      <li key={r.id} className="py-2">
                        <p className="flex items-baseline justify-between gap-3">
                          <span className="tabular font-mono font-medium">{r.return_number}</span>
                          <Money amount={r.total} currency={r.currency} size="sm" />
                        </p>
                        <p className="text-xs text-slate-600">
                          {formatDateTime(r.occurred_at, timeZone)} · {r.created_by} · {r.refund_to === "ACCOUNT" ? "off the account" : `refunded by ${r.refund_method ?? "payment"}`}
                        </p>
                        <p className="text-xs text-slate-700">
                          {r.items.map((i) => `${plainQuantity(i.quantity)} × ${i.product_name}${i.restock ? "" : " (damaged)"}`).join(", ")} · {r.reason}
                        </p>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </div>
          </div>
          <Dialog open={dialog === "void"} onClose={() => setDialog(null)} title={`Void ${data.receipt_number}`}>
            {storeId && <VoidForm sale={data} storeId={storeId} onDone={() => setDialog(null)} />}
          </Dialog>
          <Dialog open={dialog === "return"} onClose={() => setDialog(null)} title="Return items">
            {storeId && <ReturnForm sale={data} storeId={storeId} onDone={() => setDialog(null)} />}
          </Dialog>
        </>
      )}
    </>
  );
}

function Row({ label, amount, currency }: { label: string; amount: string; currency: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-slate-700">{label}</dt>
      <dd>
        <Money amount={amount} currency={currency} size="sm" tone="signed" />
      </dd>
    </div>
  );
}
