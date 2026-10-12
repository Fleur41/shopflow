"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Contact, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
import { cursorFrom } from "@/lib/lists";
import { CUSTOMERS_KEY } from "@/lib/query-keys";

import { CustomerForm } from "./CustomerForm";

export default function CustomersPage() {
  const router = useRouter();
  const { data: me } = useMe();
  const currency = me?.organization?.base_currency ?? "KES";
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [owing, setOwing] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const customers = useInfiniteQuery({
    queryKey: [...CUSTOMERS_KEY, { query, owing }],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/customers/", {
          params: { query: { cursor: pageParam, ...(query ? { search: query } : {}), ...(owing ? { has_balance: true } : {}) } },
        }),
      ),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = customers.data?.pages.flatMap((page) => page.results) ?? [];
  const seesBalances = can(me, "customers.view_balance");

  return (
    <>
      <PageHeader
        eyebrow="Selling"
        title="Customers"
        description="Regulars, their contact details and what they owe."
        actions={can(me, "customers.create") && <Button onClick={() => setAdding(true)}>Add customer</Button>}
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="relative max-w-xl flex-1">
          <TextField label="Search customers" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or phone number" className="pl-10" />
          <Search aria-hidden="true" className="pointer-events-none absolute bottom-3.5 left-3 size-4 text-slate-500" />
        </div>
        {seesBalances && (
          <label className="flex min-h-11 items-center gap-2 text-sm font-medium">
            <input type="checkbox" className="size-5 accent-emerald-700" checked={owing} onChange={(e) => setOwing(e.target.checked)} />
            Owing money
          </label>
        )}
      </div>
      {customers.isPending && <Loading label="Loading customers…" />}
      {customers.error && <ErrorAlert error={customers.error} title="Couldn't load customers" />}
      {customers.isSuccess && rows.length === 0 && (
        <EmptyState icon={query ? SearchX : Contact} title={query ? `Nothing matches “${query}”` : owing ? "Nobody owes anything" : "No customers yet"}>
          {!query && !owing && "Add regulars to sell to them on credit and keep their balance."}
        </EmptyState>
      )}
      {rows.length > 0 && (
        <div className="table-card">
          <table>
            <caption className="sr-only">Customers</caption>
            <thead>
              <tr>
                <th scope="col">Customer</th>
                {seesBalances && (
                  <>
                    <th scope="col" className="num hidden sm:table-cell">
                      Credit limit
                    </th>
                    <th scope="col" className="num">
                      Owes
                    </th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((customer) => (
                <tr key={customer.id}>
                  <td>
                    <Link href={`/customers/${customer.id}`} className="font-semibold text-slate-900 underline-offset-2 hover:text-emerald-800 hover:underline">
                      {customer.name}
                    </Link>
                    <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      <span className="tabular">{customer.phone || "No phone"}</span>
                      {customer.account?.status === "FROZEN" && <Badge tone="warning">Frozen</Badge>}
                      {!customer.is_active && <Badge>Inactive</Badge>}
                    </p>
                  </td>
                  {seesBalances && (
                    <>
                      <td className="num hidden sm:table-cell">
                        {customer.account?.credit_limit ? <Money amount={customer.account.credit_limit} currency={currency} size="sm" /> : <span className="text-sm text-slate-600">Cash only</span>}
                      </td>
                      <td className="num">
                        <Money amount={customer.account?.balance} currency={currency} />
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {customers.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={customers.isFetchingNextPage} onClick={() => customers.fetchNextPage()}>
          Load more
        </Button>
      )}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a customer">
        {adding && (
          <CustomerForm customer={null} currency={currency} canSetLimit={can(me, "customers.set_credit_limit")} onDone={(saved) => router.push(`/customers/${saved.id}`)} />
        )}
      </Dialog>
    </>
  );
}
