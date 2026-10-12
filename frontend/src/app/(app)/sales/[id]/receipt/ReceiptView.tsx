"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorAlert, Loading } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Receipt } from "@/lib/api/types";
import { useMe } from "@/lib/auth";
import { SALES_KEY } from "@/lib/query-keys";
import { formatDateTime, plainAmount, plainQuantity, useSaleStoreId } from "@/lib/sales";

type Width = "58" | "80";
const WIDTH_KEY = "shopflow:receipt-width";
const noSubscription = () => () => undefined;

function savedWidth(): Width {
  try {
    return window.localStorage.getItem(WIDTH_KEY) === "58" ? "58" : "80";
  } catch {
    return "80";
  }
}

/**
 * A printable receipt for a thermal roll. Opened from the till it prints
 * straight away; opened from a past sale it is marked COPY, and the reprint
 * is recorded in the audit log.
 */
export function ReceiptView() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const { data: me } = useMe();
  const storeId = useSaleStoreId(me);
  const reprint = params.get("reprint") === "1";
  const autoPrint = params.get("print") === "1";
  const stored = useSyncExternalStore(noSubscription, savedWidth, () => "80" as Width);
  const [chosen, setChosen] = useState<Width | null>(null);
  const width = chosen ?? stored;

  const receipt = useQuery({
    queryKey: [...SALES_KEY, storeId, id, "receipt", reprint],
    enabled: Boolean(storeId),
    staleTime: Infinity,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/sales/{sale_id}/receipt/", {
          params: { path: { store_id: storeId ?? "", sale_id: id }, query: reprint ? { reprint: true } : {} },
        }),
      ),
  });

  const printed = useRef(false);
  useEffect(() => {
    if (autoPrint && receipt.data && !printed.current) {
      printed.current = true;
      window.print();
    }
  }, [autoPrint, receipt.data]);

  function choose(next: Width) {
    setChosen(next);
    try {
      window.localStorage.setItem(WIDTH_KEY, next);
    } catch {
      // Remembered for this visit only.
    }
  }

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link href={`/sales/${id}?store=${storeId ?? ""}`} className="inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
          <ArrowLeft aria-hidden="true" className="size-4" />
          Sale
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Paper width" className="flex rounded-lg ring-1 ring-slate-300">
            {(["58", "80"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={width === option}
                onClick={() => choose(option)}
                className={`min-h-11 px-3 text-sm font-semibold first:rounded-l-lg last:rounded-r-lg ${width === option ? "bg-emerald-700 text-white" : "bg-white text-slate-800"}`}
              >
                {option} mm
              </button>
            ))}
          </div>
          <Button onClick={() => window.print()} disabled={!receipt.data}>
            <Printer aria-hidden="true" className="size-4" /> Print
          </Button>
        </div>
      </div>
      {receipt.isPending && <Loading label="Loading receipt…" />}
      {receipt.error && <ErrorAlert error={receipt.error} title="Couldn't load the receipt" />}
      {receipt.data && <PrintedReceipt receipt={receipt.data} width={width} timeZone={receipt.data.business.timezone || me?.organization?.timezone} />}
    </>
  );
}

function PrintedReceipt({ receipt, width, timeZone }: { receipt: Receipt; width: Width; timeZone: string | undefined }) {
  const { business, sale } = receipt;
  const cur = sale.currency;
  const money = (amount: string) => plainAmount(amount, cur);
  return (
    <article aria-label={`Receipt ${sale.receipt_number}`} className={`receipt receipt-${width} shadow-card ring-1 ring-slate-200`}>
      <header className="text-center">
        <p className="text-[1.2em] font-bold">{business.name}</p>
        <p>{business.store_name}</p>
        {business.address && <p>{business.address}</p>}
        {business.phone && <p>Tel {business.phone}</p>}
        {receipt.reprint && <p className="mt-1 font-bold">*** COPY ***</p>}
        {sale.status === "VOIDED" && <p className="mt-1 font-bold">*** VOID ***</p>}
      </header>
      <Rule />
      <p>Receipt {sale.receipt_number}</p>
      <p>{formatDateTime(sale.occurred_at, timeZone)}</p>
      <p>Served by {sale.cashier.name}</p>
      {sale.customer && <p>Customer {sale.customer.name}</p>}
      <Rule />
      <ul>
        {sale.items.map((item) => (
          <li key={item.line_no} className="mb-1">
            <p>{item.product_name}</p>
            <Line
              left={`${plainQuantity(item.quantity)}${item.unit_code !== "PCS" ? ` ${item.unit_code.toLowerCase()}` : ""} x ${money(item.unit_price)}`}
              right={money(item.line_total)}
            />
            {Number(item.discount_amount) > 0 && <Line left="  Discount" right={`-${money(item.discount_amount)}`} />}
          </li>
        ))}
      </ul>
      <Rule />
      {Number(sale.discount_total) > 0 && <Line left="Discounts" right={`-${money(sale.discount_total)}`} />}
      <Line left={<strong className="text-[1.15em]">TOTAL {cur}</strong>} right={<strong className="text-[1.15em]">{money(sale.total)}</strong>} />
      <Rule />
      {sale.payments.filter((payment) => payment.direction === "IN").map((payment, index) => (
        <div key={index}>
          <Line left={payment.method_name} right={money(payment.tendered ?? payment.amount)} />
          {payment.reference && <p className="pl-2">Ref {payment.reference}</p>}
        </div>
      ))}
      {Number(sale.change_given) > 0 && <Line left="Change" right={money(sale.change_given)} />}
      {Number(sale.amount_on_credit) > 0 && <Line left="On account" right={money(sale.amount_on_credit)} />}
      {receipt.account && <Line left="Account balance" right={money(receipt.account.balance_after)} />}
      {receipt.taxes.length > 0 && (
        <>
          <Rule />
          {receipt.taxes.map((tax) => (
            <Line key={tax.name} left={`${tax.name} on ${money(tax.taxable_amount)}`} right={money(tax.tax_amount)} />
          ))}
          <p>{sale.tax_mode === "INCLUSIVE" ? "Prices include tax." : "Tax added to prices."}</p>
        </>
      )}
      <Rule />
      <p className="text-center">Thank you for shopping with us!</p>
    </article>
  );
}

function Line({ left, right }: { left: ReactNode; right: ReactNode }) {
  return (
    <p className="flex justify-between gap-2">
      <span className="min-w-0">{left}</span>
      <span className="shrink-0 text-right">{right}</span>
    </p>
  );
}

function Rule() {
  return <hr className="my-1.5 border-0 border-t border-dashed border-black" />;
}
