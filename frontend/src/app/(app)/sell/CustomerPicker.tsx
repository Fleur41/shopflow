"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, UserPlus } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert, Loading } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Customer } from "@/lib/api/types";
import { CUSTOMERS_KEY } from "@/lib/query-keys";

import type { TillCustomer } from "./till-state";

export function toTillCustomer(customer: Customer): TillCustomer {
  return {
    id: customer.id,
    name: customer.name,
    balance: customer.account?.balance ?? null,
    availableCredit: customer.account?.available_credit ?? null,
  };
}

/** Find a customer by name or phone, or add a new one, for this sale. */
export function CustomerPicker({
  currency,
  canCreate,
  onPick,
}: {
  currency: string | undefined;
  canCreate: boolean;
  onPick: (customer: TillCustomer) => void;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const customers = useQuery({
    queryKey: [...CUSTOMERS_KEY, "picker", query],
    queryFn: () =>
      unwrap(api.GET("/api/v1/customers/", { params: { query: { is_active: true, page_size: 20, ...(query ? { search: query } : {}) } } })),
  });

  if (adding) return <QuickAdd initialName={/\d/.test(search) ? "" : search} initialPhone={/\d/.test(search) ? search : ""} onAdded={onPick} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="relative">
        <TextField label="Search customers" type="search" autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or phone number" className="pl-10" />
        <Search aria-hidden="true" className="pointer-events-none absolute bottom-3.5 left-3 size-4 text-slate-500" />
      </div>
      {customers.isPending && <Loading label="Finding customers…" />}
      {customers.error && <ErrorAlert error={customers.error} title="Couldn't load customers" />}
      {customers.data && (
        <ul className="flex flex-col divide-y divide-slate-100 rounded-xl ring-1 ring-slate-200" aria-label="Customers">
          {customers.data.results.length === 0 && <li className="p-4 text-sm text-slate-600">{query ? `No customer matches “${query}”.` : "No customers yet."}</li>}
          {customers.data.results.map((customer) => (
            <li key={customer.id}>
              <button
                type="button"
                onClick={() => onPick(toTillCustomer(customer))}
                className="flex min-h-14 w-full items-center justify-between gap-3 px-4 py-2 text-left hover:bg-emerald-50 focus-visible:bg-emerald-50"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{customer.name}</span>
                  <span className="tabular block text-xs text-slate-600">{customer.phone || "No phone"}</span>
                </span>
                {customer.account && (
                  <span className="shrink-0 text-right text-xs text-slate-600">
                    {Number(customer.account.balance) > 0 ? (
                      <>
                        Owes <Money amount={customer.account.balance} currency={currency} size="sm" />
                      </>
                    ) : customer.account.credit_limit ? (
                      <>
                        Credit <Money amount={customer.account.available_credit} currency={currency} size="sm" />
                      </>
                    ) : (
                      "Cash only"
                    )}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {canCreate && (
        <Button variant="secondary" onClick={() => setAdding(true)}>
          <UserPlus aria-hidden="true" className="size-4" /> New customer
        </Button>
      )}
    </div>
  );
}

function QuickAdd({ initialName, initialPhone, onAdded }: { initialName: string; initialPhone: string; onAdded: (customer: TillCustomer) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(initialName);
  const [phone, setPhone] = useState(initialPhone);
  const [key] = useState(newIdempotencyKey);
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/customers/", { body: { name, phone }, params: { header: { "Idempotency-Key": key } } })),
    onSuccess: (customer) => {
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      onAdded(toTillCustomer(customer));
    },
  });
  const errors = create.error instanceof ApiError ? create.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <TextField label="Name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
      <TextField label="Phone" type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone} hint="Helps find them next time." />
      {create.error && !Object.keys(errors).length && <ErrorAlert error={create.error} title="Couldn't add the customer" />}
      <Button type="submit" loading={create.isPending}>
        Add and use for this sale
      </Button>
    </form>
  );
}
