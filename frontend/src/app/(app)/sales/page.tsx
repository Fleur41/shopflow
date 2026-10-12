"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ReceiptText, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { SelectField, TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { cursorFrom } from "@/lib/lists";
import { SALES_KEY } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/sales";

const PERIODS = { today: "Today", week: "Last 7 days", all: "All time" } as const;
type Period = keyof typeof PERIODS;

function since(period: Period): string | undefined {
  if (period === "all") return undefined;
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  if (period === "week") start.setDate(start.getDate() - 6);
  return start.toISOString();
}

export default function SalesPage() {
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [period, setPeriod] = useState<Period>("today");
  const [creditOnly, setCreditOnly] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);
  const from = useMemo(() => since(period), [period]);
  const timeZone = me?.organization?.timezone;

  const sales = useInfiniteQuery({
    queryKey: [...SALES_KEY, store?.id, { query, from, creditOnly }],
    enabled: Boolean(store),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/sales/", {
          params: {
            path: { store_id: store?.id ?? "" },
            query: { cursor: pageParam, ...(query ? { search: query } : {}), ...(from ? { from } : {}), ...(creditOnly ? { on_credit: true } : {}) },
          },
        }),
      ),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = sales.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <PageHeader
        eyebrow={store ? `${store.code} · ${store.name}` : "Selling"}
        title="Sales"
        description={can(me, "sales.view_all") ? "Every sale at this store, newest first." : "Your sales at this store, newest first."}
        actions={
          can(me, "sales.create") && (
            <Link href="/sell" className="inline-flex min-h-11 items-center rounded-lg bg-emerald-700 px-4 text-sm font-semibold text-white hover:bg-emerald-800">
              Open the till
            </Link>
          )
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto] sm:items-end">
        <div className="relative">
          <TextField label="Receipt number" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. 000184" className="pl-10" />
          <Search aria-hidden="true" className="pointer-events-none absolute bottom-3.5 left-3 size-4 text-slate-500" />
        </div>
        <SelectField label="When" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
          {Object.entries(PERIODS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium">
          <input type="checkbox" className="size-5 accent-emerald-700" checked={creditOnly} onChange={(e) => setCreditOnly(e.target.checked)} />
          On credit only
        </label>
      </div>
      {sales.isPending && store && <Loading label="Loading sales…" />}
      {sales.error && <ErrorAlert error={sales.error} title="Couldn't load sales" />}
      {sales.isSuccess && rows.length === 0 && (
        <EmptyState icon={query ? SearchX : ReceiptText} title={query ? `No receipt matches “${query}”` : "No sales in this period"}>
          {!query && "Completed sales appear here with their receipts."}
        </EmptyState>
      )}
      {rows.length > 0 && (
        <div className="table-card">
          <table>
            <caption className="sr-only">Sales</caption>
            <thead>
              <tr>
                <th scope="col">Receipt</th>
                <th scope="col" className="hidden md:table-cell">
                  Cashier
                </th>
                <th scope="col" className="hidden sm:table-cell">
                  Paid by
                </th>
                <th scope="col" className="num">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((sale) => (
                <tr key={sale.id}>
                  <td>
                    <Link href={`/sales/${sale.id}?store=${store?.id}`} className="tabular font-mono font-semibold text-slate-900 underline-offset-2 hover:text-emerald-800 hover:underline">
                      {sale.receipt_number}
                    </Link>
                    <p className="text-xs text-slate-600">
                      {formatDateTime(sale.occurred_at, timeZone)} · {sale.item_count} {sale.item_count === 1 ? "item" : "items"}
                      {sale.customer && ` · ${sale.customer}`}
                    </p>
                  </td>
                  <td className="hidden text-slate-700 md:table-cell">{sale.cashier}</td>
                  <td className="hidden sm:table-cell">
                    <span className="flex flex-wrap gap-1">
                      {sale.methods.map((method) => (
                        <Badge key={method}>{method}</Badge>
                      ))}
                      {Number(sale.amount_on_credit) > 0 && <Badge tone="warning">Credit</Badge>}
                    </span>
                  </td>
                  <td className="num">
                    <Money amount={sale.total} currency={sale.currency} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sales.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={sales.isFetchingNextPage} onClick={() => sales.fetchNextPage()}>
          Load more
        </Button>
      )}
    </>
  );
}
