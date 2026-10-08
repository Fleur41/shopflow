"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { can, ME_KEY, useMe } from "@/lib/auth";
import { cursorFrom } from "@/lib/lists";
import { STORES_KEY } from "@/lib/query-keys";

export default function StoresPage() {
  const { data: me } = useMe();
  const [adding, setAdding] = useState(false);
  const stores = useInfiniteQuery({
    queryKey: STORES_KEY,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => unwrap(api.GET("/api/v1/stores/", { params: { query: { cursor: pageParam } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = stores.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <PageHeader
        title="Stores"
        description="Your shop locations. Each store keeps its own stock, sales and till."
        actions={can(me, "stores.manage") && <Button onClick={() => setAdding(true)}>Add store</Button>}
      />
      {stores.isPending && <Loading label="Loading stores…" />}
      {stores.error && <ErrorAlert error={stores.error} title="Couldn't load stores" />}
      {stores.isSuccess && rows.length === 0 && <EmptyState title="No stores yet" />}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-slate-200">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Stores</caption>
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th scope="col" className="px-4 py-3">Code</th>
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">Phone</th>
                <th scope="col" className="px-4 py-3">Currency</th>
                <th scope="col" className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((store) => (
                <tr key={store.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 font-mono">{store.code}</td>
                  <td className="px-4 py-3">{store.name}</td>
                  <td className="px-4 py-3">{store.phone || "—"}</td>
                  <td className="px-4 py-3">{store.currency}</td>
                  <td className="px-4 py-3">
                    {store.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {stores.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={stores.isFetchingNextPage} onClick={() => stores.fetchNextPage()}>
          Load more
        </Button>
      )}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a store">
        <AddStoreForm onDone={() => setAdding(false)} />
      </Dialog>
    </>
  );
}

function AddStoreForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  // One key per form: a double-click or retry can never create two stores.
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [form, setForm] = useState({ code: "", name: "", phone: "", address: "" });
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/", {
          body: form,
          params: { header: { "Idempotency-Key": idempotencyKey } },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: STORES_KEY }),
        queryClient.invalidateQueries({ queryKey: ME_KEY }),
      ]);
      onDone();
    },
  });
  const errors = create.error instanceof ApiError ? create.error.fieldErrors() : {};
  const set = (field: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: e.target.value }));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {create.error && !Object.keys(errors).length && <ErrorAlert error={create.error} />}
      <TextField label="Store code" required maxLength={10} value={form.code} onChange={set("code")} error={errors.code} hint="2–10 letters or digits, shown on receipt numbers. Can’t be changed later." />
      <TextField label="Store name" required value={form.name} onChange={set("name")} error={errors.name} />
      <TextField label="Phone" type="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} error={errors.phone} />
      <TextField label="Address" value={form.address} onChange={set("address")} error={errors.address} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={create.isPending}>
          Add store
        </Button>
      </div>
    </form>
  );
}
