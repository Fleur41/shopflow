"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge, Card, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useMe } from "@/lib/auth";
import { SALES_KEY } from "@/lib/query-keys";
import { formatDateTime, plainQuantity, useSaleStoreId } from "@/lib/sales";

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
                {formatDateTime(data.occurred_at, me?.organization?.timezone)} · {data.cashier.name}
              </p>
              <h1 className="tabular font-mono text-2xl font-semibold tracking-tight">{data.receipt_number}</h1>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge tone={data.status === "COMPLETED" ? "success" : "neutral"}>{data.status === "COMPLETED" ? "Completed" : "Voided"}</Badge>
                {data.customer && <Badge>{data.customer.name}</Badge>}
              </div>
            </div>
            <Link
              href={`/sales/${data.id}/receipt?store=${storeId}&reprint=1`}
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
            >
              <Printer aria-hidden="true" className="size-4" /> Reprint receipt
            </Link>
          </div>
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
                    <Row key={index} label={`${payment.method_name}${payment.reference ? ` · ${payment.reference}` : ""}`} amount={payment.amount} currency={data.currency} />
                  ))}
                  {Number(data.amount_on_credit) > 0 && <Row label={`On ${data.customer?.name ?? "account"}`} amount={data.amount_on_credit} currency={data.currency} />}
                  {Number(data.change_given) > 0 && <Row label="Change given" amount={data.change_given} currency={data.currency} />}
                </dl>
              </Card>
            </div>
          </div>
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
