"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { SelectField, TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
import { formatMoney } from "@/lib/catalog";
import { useCategories } from "@/lib/catalog-queries";
import { cursorFrom } from "@/lib/lists";
import { PRODUCTS_KEY } from "@/lib/query-keys";

import { ProductForm } from "./ProductForm";

type Status = "active" | "inactive" | "all";

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export default function ProductsPage() {
  const router = useRouter();
  const { data: me } = useMe();
  const currency = me?.organization?.base_currency;
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<Status>("active");
  const query = useDebounced(search.trim(), 300);
  const categories = useCategories();
  const categoryNames = new Map((categories.data?.results ?? []).map((c) => [c.id, c.name]));

  const products = useInfiniteQuery({
    queryKey: [...PRODUCTS_KEY, { query, status }],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/products/", {
          params: {
            query: {
              cursor: pageParam,
              ...(query ? { search: query } : {}),
              ...(status === "all" ? {} : { is_active: status === "active" }),
            },
          },
        }),
      ),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = products.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <PageHeader
        title="Products"
        description="Everything you sell. Search by name, SKU or barcode; near misses like “suger” still find sugar."
        actions={can(me, "products.manage") && <Button onClick={() => setAdding(true)}>Add product</Button>}
      />
      <div className="mb-4 grid gap-4 sm:grid-cols-[1fr_12rem]">
        <TextField label="Search products" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, SKU or barcode" />
        <SelectField label="Show" value={status} onChange={(e) => setStatus(e.target.value as Status)}>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="all">All</option>
        </SelectField>
      </div>
      {products.isPending && <Loading label="Loading products…" />}
      {products.error && <ErrorAlert error={products.error} title="Couldn't load products" />}
      {products.isSuccess && rows.length === 0 && (
        <EmptyState title={query ? `Nothing matches “${query}”` : "No products yet"}>
          {!query && can(me, "products.manage") && "Add your first product to start selling."}
        </EmptyState>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-slate-200">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Products</caption>
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th scope="col" className="w-16 px-4 py-3">
                  <span className="sr-only">Image</span>
                </th>
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">SKU</th>
                <th scope="col" className="px-4 py-3">Category</th>
                <th scope="col" className="px-4 py-3 text-right">Price</th>
                <th scope="col" className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((product) => (
                <tr key={product.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2">
                    {product.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element -- served from the media origin, already resized
                      <img src={product.thumbnail_url} alt="" width={40} height={40} className="size-10 rounded object-cover" />
                    ) : (
                      <div className="size-10 rounded bg-slate-100" aria-hidden="true" />
                    )}
                  </td>
                  <td className="px-4 py-3 font-medium">
                    <Link href={`/products/${product.id}`} className="text-emerald-800 underline-offset-2 hover:underline">
                      {product.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono">{product.sku}</td>
                  <td className="px-4 py-3">{product.category ? categoryNames.get(product.category) ?? "—" : "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatMoney(product.selling_price, currency)}</td>
                  <td className="px-4 py-3">{product.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {products.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={products.isFetchingNextPage} onClick={() => products.fetchNextPage()}>
          Load more
        </Button>
      )}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a product">
        {adding && <ProductForm product={null} onDone={(saved) => router.push(`/products/${saved.id}`)} />}
      </Dialog>
    </>
  );
}
