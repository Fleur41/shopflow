"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Vault } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { AmountField, CheckboxField, TextField } from "@/components/ui/Field";
import { Badge, Card, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Store } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { cursorFrom } from "@/lib/lists";
import { CASH_KEY, STORES_KEY } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/sales";

export default function CashPage() {
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const currency = me?.organization?.base_currency ?? "KES";
  const timeZone = me?.organization?.timezone;
  const sessions = useInfiniteQuery({
    queryKey: [...CASH_KEY, store?.id, "sessions"],
    enabled: Boolean(store),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/stores/{store_id}/cash-sessions/", { params: { path: { store_id: store?.id ?? "" }, query: { cursor: pageParam } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = sessions.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <PageHeader
        eyebrow={store ? `${store.code} · ${store.name}` : "Selling"}
        title="Till sessions"
        description="Every till from opening float to close-out count: what should have been there, and what was."
      />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div>
          {sessions.isPending && store && <Loading label="Loading till sessions…" />}
          {sessions.error && <ErrorAlert error={sessions.error} title="Couldn't load till sessions" />}
          {sessions.isSuccess && rows.length === 0 && (
            <EmptyState icon={Vault} title="No till sessions yet">
              Cashiers open the till from the Sell screen.
            </EmptyState>
          )}
          {rows.length > 0 && (
            <div className="table-card">
              <table>
                <caption className="sr-only">Till sessions</caption>
                <thead>
                  <tr>
                    <th scope="col">Session</th>
                    <th scope="col" className="num">
                      Counted
                    </th>
                    <th scope="col" className="num">
                      Difference
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((session) => {
                    const variance = session.variance === null || session.variance === undefined ? null : Number(session.variance);
                    return (
                      <tr key={session.id}>
                        <td>
                          <Link href={`/cash/${session.id}`} className="font-semibold text-slate-900 underline-offset-2 hover:text-emerald-800 hover:underline">
                            {session.till.name} · {formatDateTime(session.opened_at, timeZone)}
                          </Link>
                          <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                            {session.opened_by.name}
                            {session.status === "OPEN" && <Badge tone="success">Open</Badge>}
                          </p>
                        </td>
                        <td className="num">{session.counted_cash ? <Money amount={session.counted_cash} currency={currency} size="sm" /> : "—"}</td>
                        <td className="num">
                          {variance === null ? (
                            "—"
                          ) : variance === 0 ? (
                            <Badge tone="success">Exact</Badge>
                          ) : (
                            <span className="inline-flex items-center gap-1">
                              <Badge tone="warning">{variance < 0 ? "Short" : "Over"}</Badge>
                              <Money amount={String(session.variance).replace(/^-/, "")} currency={currency} size="sm" />
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {sessions.hasNextPage && (
            <Button variant="secondary" className="mt-4" loading={sessions.isFetchingNextPage} onClick={() => sessions.fetchNextPage()}>
              Load more
            </Button>
          )}
        </div>
        {store && can(me, "stores.manage") && <TillSettings storeId={store.id} currency={currency} />}
      </div>
    </>
  );
}

function TillSettings({ storeId, currency }: { storeId: string; currency: string }) {
  const store = useQuery({
    queryKey: [...STORES_KEY, storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/", { params: { path: { store_id: storeId } } })),
  });
  const tills = useQuery({
    queryKey: [...CASH_KEY, storeId, "tills"],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/tills/", { params: { path: { store_id: storeId } } })),
  });
  return (
    <div className="flex flex-col gap-6">
      {store.data && <PolicyCard key={`${store.data.require_cash_session}-${store.data.cash_variance_threshold}`} store={store.data} currency={currency} />}
      <Card title="Tills" description="Each cash drawer in this store.">
        {tills.data && (
          <ul className="mb-4 flex flex-col divide-y divide-slate-100">
            {tills.data.map((till) => (
              <li key={till.id} className="flex items-center justify-between py-2 text-sm">
                {till.name}
                {!till.is_active && <Badge>Inactive</Badge>}
              </li>
            ))}
          </ul>
        )}
        <AddTill storeId={storeId} />
      </Card>
    </div>
  );
}

function PolicyCard({ store, currency }: { store: Store; currency: string }) {
  const queryClient = useQueryClient();
  const [required, setRequired] = useState(store.require_cash_session ?? true);
  const [threshold, setThreshold] = useState(Number(store.cash_variance_threshold ?? 0).toFixed(2));
  const save = useMutation({
    mutationFn: () =>
      unwrap(api.PATCH("/api/v1/stores/{store_id}/", { params: { path: { store_id: store.id } }, body: { require_cash_session: required, cash_variance_threshold: threshold || "0" } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: STORES_KEY }),
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Card title="Till rules">
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <CheckboxField label="Cash sales need an open till" checked={required} onChange={(e) => setRequired(e.target.checked)} hint="So every shilling taken is counted at close-out." />
        <AmountField
          label="Allowed difference at close"
          currency={currency}
          value={threshold}
          onValueChange={setThreshold}
          error={errors.cash_variance_threshold}
          hint="A count further out than this needs a reason and is flagged."
        />
        {save.error && !Object.keys(errors).length ? <ErrorAlert error={save.error} title="Couldn't save" /> : null}
        <p role="status" className="sr-only">
          {save.isSuccess ? "Saved." : ""}
        </p>
        <Button type="submit" variant="secondary" loading={save.isPending}>
          Save rules
        </Button>
      </form>
    </Card>
  );
}

function AddTill({ storeId }: { storeId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/stores/{store_id}/tills/", { params: { path: { store_id: storeId }, header: { "Idempotency-Key": key } }, body: { name } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CASH_KEY });
      setName("");
      setKey(newIdempotencyKey());
    },
  });
  const errors = add.error instanceof ApiError ? add.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex items-end gap-2">
      <div className="min-w-0 flex-1">
        <TextField label="New till" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} placeholder="e.g. Till 2" />
      </div>
      <Button type="submit" variant="secondary" loading={add.isPending} disabled={!name.trim()}>
        Add
      </Button>
    </form>
  );
}
