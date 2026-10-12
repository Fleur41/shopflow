"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { AmountField, CheckboxField, TextField } from "@/components/ui/Field";
import { Card, EmptyState, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Movement, StockRow } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { cursorFrom } from "@/lib/lists";
import { INVENTORY_KEY } from "@/lib/query-keys";
import { formatDateTime, plainQuantity } from "@/lib/sales";

import { AdjustForm, REASONS } from "../AdjustForm";
import { StockBadge } from "../StockBadge";

const MOVEMENT_LABELS: Record<string, string> = {
  SALE: "Sale",
  OPENING: "Opening stock",
  ADJUSTMENT: "Adjustment",
  DAMAGED: "Damaged",
  EXPIRED: "Expired",
  PURCHASE: "Received",
  SALE_RETURN: "Returned by customer",
  PURCHASE_RETURN: "Returned to supplier",
  TRANSFER_IN: "Transfer in",
  TRANSFER_OUT: "Transfer out",
};

export default function StockPage() {
  const { productId } = useParams<{ productId: string }>();
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const currency = me?.organization?.base_currency ?? "KES";
  const [adjusting, setAdjusting] = useState(false);
  const row = useQuery({
    queryKey: [...INVENTORY_KEY, store?.id, productId],
    enabled: Boolean(store),
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/inventory/{product_id}/", { params: { path: { store_id: store?.id ?? "", product_id: productId } } })),
  });

  return (
    <>
      <Link href="/inventory" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" />
        All stock
      </Link>
      {row.isPending && store && <Loading label="Loading stock…" />}
      {row.error && <ErrorAlert error={row.error} title="Couldn't load this product's stock" />}
      {row.data && store && (
        <>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-emerald-800">
                {store.code} · {store.name}
              </p>
              <h1 className="text-2xl font-semibold tracking-tight">{row.data.name}</h1>
              <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                <Link href={`/products/${productId}`} className="tabular font-mono underline-offset-2 hover:underline">
                  {row.data.sku}
                </Link>
                <StockBadge status={row.data.stock_status} />
              </p>
            </div>
            <div className="flex items-end gap-4">
              <div className="text-right">
                <p className="text-sm text-slate-600">In stock</p>
                <p className="tabular text-4xl font-semibold tracking-tight">
                  {plainQuantity(row.data.quantity_on_hand)} <span className="text-lg font-medium text-slate-600">{row.data.unit.name.toLowerCase()}</span>
                </p>
              </div>
              {can(me, "inventory.adjust") && <Button onClick={() => setAdjusting(true)}>Adjust</Button>}
            </div>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            {can(me, "inventory.view_movements") ? (
              <MovementsCard storeId={store.id} productId={productId} timeZone={me?.organization?.timezone} />
            ) : (
              <Card title="History">
                <p className="text-sm text-slate-600">You don’t have access to stock history.</p>
              </Card>
            )}
            <div className="flex flex-col gap-6">
              <Card title="Value">
                <dl className="flex flex-col gap-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-slate-600">Selling price here</dt>
                    <dd>
                      <Money amount={row.data.price} currency={currency} size="sm" />
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-600">Average cost</dt>
                    <dd>
                      <Money amount={row.data.average_cost} currency={currency} size="sm" />
                    </dd>
                  </div>
                </dl>
              </Card>
              <SettingsCard key={row.data.version} storeId={store.id} row={row.data} currency={currency} me={me} />
            </div>
          </div>
          <Dialog open={adjusting} onClose={() => setAdjusting(false)} title={`Adjust ${row.data.name}`}>
            <AdjustForm storeId={store.id} row={row.data} currency={currency} onDone={() => setAdjusting(false)} />
          </Dialog>
        </>
      )}
    </>
  );
}

function MovementsCard({ storeId, productId, timeZone }: { storeId: string; productId: string; timeZone: string | undefined }) {
  const movements = useInfiniteQuery({
    queryKey: [...INVENTORY_KEY, storeId, productId, "movements"],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/stores/{store_id}/inventory/movements/", { params: { path: { store_id: storeId }, query: { product: productId, cursor: pageParam, page_size: 25 } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = movements.data?.pages.flatMap((page) => page.results) ?? [];
  return (
    <Card title="History" description="Every change to this product's stock here, newest first.">
      {movements.isPending && <Loading label="Loading history…" />}
      {movements.error && <ErrorAlert error={movements.error} title="Couldn't load the history" />}
      {movements.isSuccess && rows.length === 0 && <EmptyState title="No changes yet">Record the opening stock to start its history.</EmptyState>}
      {rows.length > 0 && (
        <ol className="flex flex-col divide-y divide-slate-100">
          {rows.map((movement) => (
            <MovementRow key={movement.id} movement={movement} storeId={storeId} timeZone={timeZone} />
          ))}
        </ol>
      )}
      {movements.hasNextPage && (
        <Button variant="secondary" className="mt-3" loading={movements.isFetchingNextPage} onClick={() => movements.fetchNextPage()}>
          Older changes
        </Button>
      )}
    </Card>
  );
}

function MovementRow({ movement, storeId, timeZone }: { movement: Movement; storeId: string; timeZone: string | undefined }) {
  const quantity = plainQuantity(movement.quantity);
  const added = !quantity.startsWith("-");
  const document = movement.document as { kind?: string; id?: string; receipt_number?: string; reason_code?: string; note?: string } | null;
  const label =
    document?.kind === "adjustment" && document.reason_code
      ? (REASONS[document.reason_code as keyof typeof REASONS]?.label ?? MOVEMENT_LABELS[movement.movement_type])
      : MOVEMENT_LABELS[movement.movement_type];
  return (
    <li className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="font-medium">
          {label}
          {document?.kind === "sale" && document.id && (
            <>
              {" "}
              <Link href={`/sales/${document.id}?store=${storeId}`} className="tabular font-mono text-sm text-emerald-800 underline-offset-2 hover:underline">
                {document.receipt_number}
              </Link>
            </>
          )}
        </p>
        <p className="text-xs text-slate-600">
          {formatDateTime(movement.occurred_at, timeZone)} · {movement.performed_by}
          {document?.note ? ` · ${document.note}` : ""}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className={`tabular font-semibold ${added ? "text-emerald-800" : "text-red-800"}`}>
          {added ? "+" : "−"}
          {quantity.replace(/^-/, "")}
        </p>
        <p className="tabular text-xs text-slate-600">→ {plainQuantity(movement.quantity_after)}</p>
      </div>
    </li>
  );
}

function SettingsCard({ storeId, row, currency, me }: { storeId: string; row: StockRow; currency: string; me: Parameters<typeof can>[0] }) {
  const queryClient = useQueryClient();
  const canLevels = can(me, "inventory.manage_levels");
  const canPrice = can(me, "products.change_price");
  const canPolicy = can(me, "stores.manage_inventory_policy");
  const [reorder, setReorder] = useState(row.reorder_level ? plainQuantity(row.reorder_level) : "");
  const [minimum, setMinimum] = useState(row.min_stock ? plainQuantity(row.min_stock) : "");
  const [maximum, setMaximum] = useState(row.max_stock ? plainQuantity(row.max_stock) : "");
  const [price, setPrice] = useState(row.selling_price_override ?? "");
  const [allowNegative, setAllowNegative] = useState(row.allow_negative);
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { version: row.version };
      if (canLevels) Object.assign(body, { reorder_level: reorder || null, min_stock: minimum || null, max_stock: maximum || null });
      if (canPrice) body.selling_price_override = price || null;
      if (canPolicy) body.allow_negative = allowNegative;
      return unwrap(
        api.PATCH("/api/v1/stores/{store_id}/inventory/{product_id}/", {
          params: { path: { store_id: storeId, product_id: row.product_id } },
          body: body as { version: number },
        }),
      );
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: INVENTORY_KEY }),
  });
  if (!canLevels && !canPrice && !canPolicy) return null;
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Card title="Settings for this store">
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        {canLevels && (
          <>
            <TextField
              label="Reorder when stock reaches"
              inputMode="decimal"
              value={reorder}
              onChange={(e) => setReorder(e.target.value.trim())}
              error={errors.reorder_level}
              hint={row.effective_reorder_level && !row.reorder_level ? `Empty: the product's default (${plainQuantity(row.effective_reorder_level)}).` : undefined}
            />
            <div className="grid grid-cols-2 gap-3">
              <TextField label="Minimum" inputMode="decimal" value={minimum} onChange={(e) => setMinimum(e.target.value.trim())} error={errors.min_stock} />
              <TextField label="Maximum" inputMode="decimal" value={maximum} onChange={(e) => setMaximum(e.target.value.trim())} error={errors.max_stock} />
            </div>
          </>
        )}
        {canPrice && (
          <AmountField
            label="Price at this store"
            currency={currency}
            value={price}
            onValueChange={setPrice}
            error={errors.selling_price_override}
            hint="Empty: the product's normal price."
          />
        )}
        {canPolicy && (
          <CheckboxField
            label="Allow selling below zero"
            checked={allowNegative}
            onChange={(e) => setAllowNegative(e.target.checked)}
            hint="Sales go through even if the system shows no stock; count it later."
          />
        )}
        {save.error && !Object.keys(errors).length ? <ErrorAlert error={save.error} title="Couldn't save" /> : null}
        <p role="status" className="sr-only">
          {save.isSuccess ? "Saved." : ""}
        </p>
        <Button type="submit" variant="secondary" loading={save.isPending}>
          Save settings
        </Button>
      </form>
    </Card>
  );
}
