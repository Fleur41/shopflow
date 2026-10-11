"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Package, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { SelectField, TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
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
        eyebrow="Catalog"
        title="Products"
        description="Everything you sell. Search by name, SKU or barcode; near misses like “suger” still find sugar."
        actions={can(me, "products.manage") && <Button onClick={() => setAdding(true)}>Add product</Button>}
      />
      <div className="mb-4 grid gap-4 sm:grid-cols-[1fr_12rem]">
        <div className="relative">
          <TextField label="Search products" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, SKU or barcode" className="pl-10" />
          <Search aria-hidden="true" className="pointer-events-none absolute bottom-3.5 left-3 size-4 text-slate-500" />
        </div>
        <SelectField label="Show" value={status} onChange={(e) => setStatus(e.target.value as Status)}>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="all">All</option>
        </SelectField>
      </div>
      {products.isPending && <Loading label="Loading products…" />}
      {products.error && <ErrorAlert error={products.error} title="Couldn't load products" />}
      {products.isSuccess && rows.length === 0 && (
        <EmptyState icon={query ? SearchX : Package} title={query ? `Nothing matches “${query}”` : "No products yet"}>
          {!query && can(me, "products.manage") && "Add your first product to start selling."}
        </EmptyState>
      )}
      {rows.length > 0 && (
        <div className="table-card">
          <table>
            <caption className="sr-only">Products</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col" className="hidden md:table-cell">
                  Category
                </th>
                <th scope="col" className="num">
                  Price
                </th>
                <th scope="col" className="hidden sm:table-cell">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((product) => (
                <tr key={product.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      {product.thumbnail_url ? (
                        // eslint-disable-next-line @next/next/no-img-element -- served from the media origin, already resized
                        <img src={product.thumbnail_url} alt="" width={44} height={44} className="size-11 shrink-0 rounded-lg object-cover ring-1 ring-slate-200" />
                      ) : (
                        <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 ring-1 ring-slate-200">
                          <Package className="size-5" />
                        </span>
                      )}
                      <div className="min-w-0">
                        <Link href={`/products/${product.id}`} className="font-semibold text-slate-900 underline-offset-2 hover:text-emerald-800 hover:underline">
                          {product.name}
                        </Link>
                        <p className="tabular truncate font-mono text-xs text-slate-600">{product.sku}</p>
                      </div>
                    </div>
                  </td>
                  <td className="hidden text-slate-700 md:table-cell">{product.category ? categoryNames.get(product.category) ?? "—" : "—"}</td>
                  <td className="num">
                    <Money amount={product.selling_price} currency={currency} />
                  </td>
                  <td className="hidden sm:table-cell">{product.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>}</td>
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
