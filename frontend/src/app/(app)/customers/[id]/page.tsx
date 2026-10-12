"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Mail, MapPin, Phone } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { AmountField, SelectField, TextField } from "@/components/ui/Field";
import { Badge, Card, EmptyState, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Customer, CustomerAccount, LedgerEntry } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { cursorFrom } from "@/lib/lists";
import { CUSTOMERS_KEY, PAYMENT_METHODS_KEY } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/sales";

import { CustomerForm } from "../CustomerForm";

const ENTRY_LABELS: Record<string, string> = {
  OPENING_BALANCE: "Opening balance",
  CREDIT_SALE: "Credit sale",
  PAYMENT: "Payment",
  SALE_RETURN: "Return",
  ADJUSTMENT: "Adjustment",
  REVERSAL: "Reversal",
};

export default function CustomerPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const currency = me?.organization?.base_currency ?? "KES";
  const [editing, setEditing] = useState(false);
  const customer = useQuery({
    queryKey: [...CUSTOMERS_KEY, id],
    queryFn: () => unwrap(api.GET("/api/v1/customers/{entry_id}/", { params: { path: { entry_id: id } } })),
  });
  const data = customer.data;

  return (
    <>
      <Link href="/customers" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" />
        All customers
      </Link>
      {customer.isPending && <Loading label="Loading customer…" />}
      {customer.error && <ErrorAlert error={customer.error} title="Couldn't load this customer" />}
      {data && (
        <>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">{data.name}</h1>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-700">
                {data.phone && (
                  <li className="inline-flex items-center gap-1.5">
                    <Phone aria-hidden="true" className="size-4 text-slate-500" />
                    <span className="tabular">{data.phone}</span>
                  </li>
                )}
                {data.email && (
                  <li className="inline-flex min-w-0 items-center gap-1.5 break-all">
                    <Mail aria-hidden="true" className="size-4 text-slate-500" /> {data.email}
                  </li>
                )}
                {data.address && (
                  <li className="inline-flex items-center gap-1.5">
                    <MapPin aria-hidden="true" className="size-4 text-slate-500" /> {data.address}
                  </li>
                )}
              </ul>
            </div>
            {can(me, "customers.manage") && (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                Edit details
              </Button>
            )}
          </div>
          {data.account ? (
            <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              <LedgerCard customerId={id} currency={currency} canReverse={can(me, "customers.reverse_entry")} timeZone={me?.organization?.timezone} />
              <div className="flex flex-col gap-6">
                <AccountCard customer={data} account={data.account} currency={currency} me={me} />
              </div>
            </div>
          ) : (
            <Card title="Account">
              <p className="text-sm text-slate-600">You don’t have access to this customer’s balance.</p>
            </Card>
          )}
          <Dialog open={editing} onClose={() => setEditing(false)} title="Edit customer">
            <CustomerForm key={data.version} customer={data} currency={currency} canSetLimit={false} onDone={() => setEditing(false)} />
          </Dialog>
        </>
      )}
    </>
  );
}

function AccountCard({ customer, account, currency, me }: { customer: Customer; account: CustomerAccount; currency: string; me: Parameters<typeof can>[0] }) {
  const [paying, setPaying] = useState(false);
  const [limits, setLimits] = useState(false);
  const [opening, setOpening] = useState(false);
  const owes = Number(account.balance) > 0;
  return (
    <Card title="Account" actions={account.status !== "ACTIVE" && <Badge tone="warning">{account.status === "FROZEN" ? "Frozen" : "Closed"}</Badge>}>
      <div className="rounded-xl bg-ledger-900 px-5 py-4 text-white">
        <p className="text-sm text-emerald-100/80">{owes ? "Owes" : "Balance"}</p>
        <Money amount={account.balance} currency={currency} size="xl" tone="inverse" />
      </div>
      <dl className="mt-4 flex flex-col gap-2 text-sm">
        <div className="flex justify-between">
          <dt className="text-slate-600">Credit limit</dt>
          <dd>{account.credit_limit ? <Money amount={account.credit_limit} currency={currency} size="sm" /> : "Cash only"}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-600">Can still take</dt>
          <dd>
            <Money amount={account.available_credit} currency={currency} size="sm" />
          </dd>
        </div>
      </dl>
      <div className="mt-4 flex flex-col gap-2">
        {owes && can(me, "customers.receive_payment") && <Button onClick={() => setPaying(true)}>Receive payment</Button>}
        {can(me, "customers.set_credit_limit") && (
          <Button variant="secondary" onClick={() => setLimits(true)}>
            Credit limit and status
          </Button>
        )}
        {can(me, "customers.set_credit_limit") && !owes && (
          <Button variant="ghost" onClick={() => setOpening(true)}>
            Record what they already owe
          </Button>
        )}
      </div>
      <Dialog open={paying} onClose={() => setPaying(false)} title={`Payment from ${customer.name}`}>
        <PaymentForm customerId={customer.id} balance={account.balance} currency={currency} me={me} onDone={() => setPaying(false)} />
      </Dialog>
      <Dialog open={limits} onClose={() => setLimits(false)} title="Credit limit and status">
        <LimitsForm customerId={customer.id} account={account} currency={currency} onDone={() => setLimits(false)} />
      </Dialog>
      <Dialog open={opening} onClose={() => setOpening(false)} title="Opening balance" description="What they owed before you started using ShopFlow. Only possible before any other entry.">
        <OpeningForm customerId={customer.id} currency={currency} onDone={() => setOpening(false)} />
      </Dialog>
    </Card>
  );
}

function PaymentForm({ customerId, balance, currency, me, onDone }: { customerId: string; balance: string; currency: string; me: Parameters<typeof can>[0]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [store] = useCurrentStore(me);
  const [ids] = useState(() => ({ key: newIdempotencyKey(), txn: crypto.randomUUID() }));
  const [amount, setAmount] = useState("");
  const [methodId, setMethodId] = useState("");
  const [reference, setReference] = useState("");
  const methods = useQuery({
    queryKey: [...PAYMENT_METHODS_KEY, "till"],
    queryFn: () => unwrap(api.GET("/api/v1/payment-methods/", { params: { query: { is_active: true, page_size: 50 } } })),
    select: (page) => [...page.results].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)),
  });
  const method = methods.data?.find((m) => m.id === methodId) ?? methods.data?.[0];
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/customers/{customer_id}/payments/", {
          params: { path: { customer_id: customerId }, header: { "Idempotency-Key": ids.key } },
          body: { client_txn_id: ids.txn, store_id: store?.id ?? "", payment_method_id: method?.id ?? "", amount, reference },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      onDone();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  const needsCode = method?.requires_reference || method?.kind === "MOBILE_MONEY";
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <p className="text-sm text-slate-700">
        Owes <Money amount={balance} currency={currency} size="sm" />. Payments can’t be more than that.
      </p>
      <AmountField label="Amount" required currency={currency} value={amount} onValueChange={setAmount} error={errors.amount} autoFocus />
      <button type="button" className="-mt-2 self-start text-sm font-medium text-emerald-800 underline" onClick={() => setAmount(Number(balance).toFixed(2))}>
        Pays everything
      </button>
      <SelectField label="Paid with" value={method?.id ?? ""} onChange={(e) => setMethodId(e.target.value)}>
        {methods.data?.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </SelectField>
      {needsCode && (
        <TextField
          label={method?.kind === "MOBILE_MONEY" ? `${method.name} code` : "Reference"}
          required={method?.requires_reference}
          value={reference}
          onChange={(e) => setReference(e.target.value.toUpperCase())}
          error={errors.reference}
          autoCapitalize="characters"
          className="tabular font-mono uppercase"
        />
      )}
      <p className="text-xs text-slate-600">Recorded at {store ? `${store.name} (${store.code})` : "your store"}.</p>
      {save.error && !Object.keys(errors).length ? <ErrorAlert error={save.error} title="Couldn't record the payment" /> : null}
      <Button type="submit" loading={save.isPending} disabled={!store || !method}>
        Record payment
      </Button>
    </form>
  );
}

function LimitsForm({ customerId, account, currency, onDone }: { customerId: string; account: CustomerAccount; currency: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [limit, setLimit] = useState(account.credit_limit ? Number(account.credit_limit).toFixed(2) : "");
  const [status, setStatus] = useState(account.status);
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/customers/{customer_id}/account/", {
          params: { path: { customer_id: customerId } },
          body: { version: account.version, credit_limit: limit || null, status },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      onDone();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <AmountField label="Credit limit" currency={currency} value={limit} onValueChange={setLimit} error={errors.credit_limit} hint="Empty: cash only." />
      <SelectField label="Account" value={status} onChange={(e) => setStatus(e.target.value as CustomerAccount["status"])}>
        <option value="ACTIVE">Active</option>
        <option value="FROZEN">Frozen: no new credit</option>
        <option value="CLOSED">Closed</option>
      </SelectField>
      {save.error && !Object.keys(errors).length ? <ErrorAlert error={save.error} title="Couldn't save" /> : null}
      <Button type="submit" loading={save.isPending}>
        Save
      </Button>
    </form>
  );
}

function OpeningForm({ customerId, currency, onDone }: { customerId: string; currency: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/customers/{customer_id}/account/opening-balance/", {
          params: { path: { customer_id: customerId }, header: { "Idempotency-Key": key } },
          body: { amount, note },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      onDone();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <AmountField label="They owe" required currency={currency} value={amount} onValueChange={setAmount} error={errors.amount} autoFocus />
      <TextField label="Note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. From the old credit book" />
      {save.error && !Object.keys(errors).length ? <ErrorAlert error={save.error} title="Couldn't save" /> : null}
      <Button type="submit" loading={save.isPending}>
        Save
      </Button>
    </form>
  );
}

function LedgerCard({ customerId, currency, canReverse, timeZone }: { customerId: string; currency: string; canReverse: boolean; timeZone: string | undefined }) {
  const [reversing, setReversing] = useState<LedgerEntry | null>(null);
  const ledger = useInfiniteQuery({
    queryKey: [...CUSTOMERS_KEY, customerId, "ledger"],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => unwrap(api.GET("/api/v1/customers/{customer_id}/ledger/", { params: { path: { customer_id: customerId }, query: { cursor: pageParam } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = ledger.data?.pages.flatMap((page) => page.results) ?? [];
  return (
    <Card title="Statement" description="Every sale on credit and every payment, newest first.">
      {ledger.isPending && <Loading label="Loading statement…" />}
      {ledger.error && <ErrorAlert error={ledger.error} title="Couldn't load the statement" />}
      {ledger.isSuccess && rows.length === 0 && <EmptyState title="Nothing yet">Credit sales and payments will appear here.</EmptyState>}
      {rows.length > 0 && (
        <ol className="flex flex-col divide-y divide-slate-100">
          {rows.map((entry) => (
            <li key={entry.id} className="flex items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="font-medium">
                  {ENTRY_LABELS[entry.entry_type] ?? entry.entry_type}
                  {entry.receipt_number && entry.sale_id && (
                    <>
                      {" "}
                      <Link href={`/sales/${entry.sale_id}${entry.store_id ? `?store=${entry.store_id}` : ""}`} className="tabular font-mono text-sm text-emerald-800 underline-offset-2 hover:underline">
                        {entry.receipt_number}
                      </Link>
                    </>
                  )}
                  {entry.reversed && <span className="ml-2 align-middle"><Badge>Reversed</Badge></span>}
                </p>
                <p className="text-xs text-slate-600">
                  {formatDateTime(entry.occurred_at, timeZone)} · {entry.created_by}
                  {entry.description && entry.entry_type !== "CREDIT_SALE" ? ` · ${entry.description}` : ""}
                </p>
                {canReverse && !entry.reversed && (entry.entry_type === "PAYMENT" || entry.entry_type === "OPENING_BALANCE") && (
                  <button type="button" onClick={() => setReversing(entry)} className="mt-1 min-h-11 text-sm font-medium text-red-800 underline sm:min-h-0">
                    Reverse
                  </button>
                )}
              </div>
              <div className="shrink-0 text-right">
                <Money amount={entry.amount} currency={currency} tone="signed" />
                <p className="text-xs text-slate-600">
                  Balance <Money amount={entry.balance_after} currency={currency} size="sm" />
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
      {ledger.hasNextPage && (
        <Button variant="secondary" className="mt-3" loading={ledger.isFetchingNextPage} onClick={() => ledger.fetchNextPage()}>
          Older entries
        </Button>
      )}
      <Dialog open={reversing !== null} onClose={() => setReversing(null)} title="Reverse this entry" description="An opposite entry is added; nothing is deleted.">
        {reversing && <ReverseForm customerId={customerId} entry={reversing} onDone={() => setReversing(null)} />}
      </Dialog>
    </Card>
  );
}

function ReverseForm({ customerId, entry, onDone }: { customerId: string; entry: LedgerEntry; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/customers/{customer_id}/ledger/{entry_id}/reverse/", {
          params: { path: { customer_id: customerId, entry_id: entry.id }, header: { "Idempotency-Key": key } },
          body: { reason },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      onDone();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <TextField label="Why?" required value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} autoFocus placeholder="e.g. Recorded on the wrong customer" />
      {save.error && !errors.reason ? <ErrorAlert error={save.error} title="Couldn't reverse it" /> : null}
      <Button type="submit" variant="danger" loading={save.isPending}>
        Reverse entry
      </Button>
    </form>
  );
}
