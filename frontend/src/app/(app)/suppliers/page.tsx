"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Search, SearchX, Truck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
import { cursorFrom } from "@/lib/lists";
import { SUPPLIERS_KEY } from "@/lib/query-keys";

import { SupplierForm, paymentTerms } from "./SupplierForm";

export default function SuppliersPage() {
  const router = useRouter();
  const { data: me } = useMe();
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const suppliers = useInfiniteQuery({
    queryKey: [...SUPPLIERS_KEY, { query }],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/suppliers/", { params: { query: { cursor: pageParam, ...(query ? { search: query } : {}) } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = suppliers.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Buying"
        title="Suppliers"
        description="Who you buy from, how to reach them, and how long you have to pay."
        actions={can(me, "suppliers.manage") && <Button onClick={() => setAdding(true)}>Add supplier</Button>}
      />
      <div className="relative mb-4 max-w-xl">
        <TextField label="Search suppliers" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, code, phone or KRA PIN" className="pl-10" />
        <Search aria-hidden="true" className="pointer-events-none absolute bottom-3.5 left-3 size-4 text-slate-500" />
      </div>
      {suppliers.isPending && <Loading label="Loading suppliers…" />}
      {suppliers.error && <ErrorAlert error={suppliers.error} title="Couldn't load suppliers" />}
      {suppliers.isSuccess && rows.length === 0 && (
        <EmptyState icon={query ? SearchX : Truck} title={query ? `Nothing matches “${query}”` : "No suppliers yet"}>
          {!query && "Add the businesses you buy stock from."}
        </EmptyState>
      )}
      {rows.length > 0 && (
        <div className="table-card">
          <table>
            <caption className="sr-only">Suppliers</caption>
            <thead>
              <tr>
                <th scope="col">Supplier</th>
                <th scope="col" className="hidden md:table-cell">
                  Phone
                </th>
                <th scope="col">Payment terms</th>
                <th scope="col" className="hidden sm:table-cell">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((supplier) => (
                <tr key={supplier.id}>
                  <td>
                    <Link href={`/suppliers/${supplier.id}`} className="font-semibold text-slate-900 underline-offset-2 hover:text-emerald-800 hover:underline">
                      {supplier.name}
                    </Link>
                    <p className="tabular font-mono text-xs text-slate-600">
                      {supplier.code}
                      {supplier.kra_pin && ` · ${supplier.kra_pin}`}
                    </p>
                  </td>
                  <td className="tabular hidden text-slate-700 md:table-cell">{supplier.phone || "—"}</td>
                  <td className="tabular">{paymentTerms(supplier.payment_terms_days)}</td>
                  <td className="hidden sm:table-cell">{supplier.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {suppliers.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={suppliers.isFetchingNextPage} onClick={() => suppliers.fetchNextPage()}>
          Load more
        </Button>
      )}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a supplier">
        {adding && <SupplierForm supplier={null} onDone={(saved) => router.push(`/suppliers/${saved.id}`)} />}
      </Dialog>
    </>
  );
}
