"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Boxes, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { TextField } from "@/components/ui/Field";
import { EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { StockRow } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { cursorFrom } from "@/lib/lists";
import { INVENTORY_KEY } from "@/lib/query-keys";
import { plainQuantity } from "@/lib/sales";

import { AdjustForm } from "./AdjustForm";
import { StockBadge } from "./StockBadge";

const FILTERS = { "": "All", low: "Running low", out: "Out of stock" } as const;
type Filter = keyof typeof FILTERS;

export default function InventoryPage() {
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const currency = me?.organization?.base_currency ?? "KES";
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("");
  const [adjusting, setAdjusting] = useState<StockRow | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const stock = useInfiniteQuery({
    queryKey: [...INVENTORY_KEY, store?.id, { query, filter }],
    enabled: Boolean(store),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/inventory/", {
          params: {
            path: { store_id: store?.id ?? "" },
            query: { cursor: pageParam, is_active: true, ...(query ? { search: query } : {}), ...(filter ? { stock_status: filter } : {}) },
          },
        }),
      ),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = stock.data?.pages.flatMap((page) => page.results) ?? [];
  const canAdjust = can(me, "inventory.adjust");

  return (
    <>
      <PageHeader
        eyebrow={store ? `${store.code} · ${store.name}` : "Catalog"}
        title="Stock"
        description="What this store holds, what's running low, and every change to it."
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="relative max-w-xl flex-1">
          <TextField label="Search stock" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, SKU or barcode" className="pl-10" />
          <Search aria-hidden="true" className="pointer-events-none absolute bottom-3.5 left-3 size-4 text-slate-500" />
        </div>
        <div role="group" aria-label="Show" className="flex rounded-lg ring-1 ring-slate-300">
          {(Object.keys(FILTERS) as Filter[]).map((value) => (
            <button
              key={value || "all"}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className={`min-h-11 min-w-11 flex-1 whitespace-nowrap px-3 text-sm font-semibold first:rounded-l-lg last:rounded-r-lg ${filter === value ? "bg-emerald-700 text-white" : "bg-white text-slate-800 hover:bg-slate-50"}`}
            >
              {FILTERS[value]}
            </button>
          ))}
        </div>
      </div>
      {stock.isPending && store && <Loading label="Loading stock…" />}
      {stock.error && <ErrorAlert error={stock.error} title="Couldn't load stock" />}
      {stock.isSuccess && rows.length === 0 && (
        <EmptyState icon={query || filter ? SearchX : Boxes} title={query ? `Nothing matches “${query}”` : filter ? `Nothing ${FILTERS[filter].toLowerCase()}` : "No stocked products yet"}>
          {!query && !filter && "Products you add appear here; record their opening stock to start."}
        </EmptyState>
      )}
      {rows.length > 0 && (
        <div className="table-card">
          <table>
            <caption className="sr-only">Stock levels</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col" className="num">
                  In stock
                </th>
                <th scope="col" className="num hidden sm:table-cell">
                  Reorder at
                </th>
                {canAdjust && (
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.product_id}>
                  <td>
                    <Link href={`/inventory/${row.product_id}`} className="font-semibold text-slate-900 underline-offset-2 hover:text-emerald-800 hover:underline">
                      {row.name}
                    </Link>
                    <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      <span className="tabular font-mono">{row.sku}</span>
                      <StockBadge status={row.stock_status} />
                    </p>
                  </td>
                  <td className="num tabular font-semibold">
                    {plainQuantity(row.quantity_on_hand)} <span className="font-normal text-slate-600">{row.unit.code.toLowerCase()}</span>
                  </td>
                  <td className="num tabular hidden text-slate-700 sm:table-cell">{row.effective_reorder_level ? plainQuantity(row.effective_reorder_level) : "—"}</td>
                  {canAdjust && (
                    <td className="num">
                      <Button variant="secondary" onClick={() => setAdjusting(row)} aria-label={`Adjust ${row.name}`}>
                        Adjust
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {stock.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={stock.isFetchingNextPage} onClick={() => stock.fetchNextPage()}>
          Load more
        </Button>
      )}
      <Dialog open={adjusting !== null} onClose={() => setAdjusting(null)} title={adjusting ? `Adjust ${adjusting.name}` : "Adjust stock"}>
        {adjusting && store && <AdjustForm storeId={store.id} row={adjusting} currency={currency} onDone={() => setAdjusting(null)} />}
      </Dialog>
    </>
  );
}
