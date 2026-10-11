"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Product } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { formatMoney } from "@/lib/catalog";
import { PRODUCTS_KEY } from "@/lib/query-keys";

import { ProductForm } from "../ProductForm";

export default function ProductPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const canManage = can(me, "products.manage");
  const [saved, setSaved] = useState(false);
  const product = useQuery({
    queryKey: [...PRODUCTS_KEY, id],
    queryFn: () => unwrap(api.GET("/api/v1/products/{entry_id}/", { params: { path: { entry_id: id } } })),
  });

  return (
    <>
      <p className="mb-2 text-sm">
        <Link href="/products" className="text-emerald-800 underline-offset-2 hover:underline">
          ← All products
        </Link>
      </p>
      {product.isPending && <Loading label="Loading product…" />}
      {product.error && <ErrorAlert error={product.error} title="Couldn't load this product" />}
      {product.data && (
        <>
          <PageHeader title={product.data.name} description={`SKU ${product.data.sku}${product.data.is_active ? "" : " · inactive"}`} />
          <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <Card title="Details">
              <p role="status" className="sr-only">
                {saved ? "Changes saved." : ""}
              </p>
              {canManage ? (
                <ProductForm key={product.data.version} product={product.data} onDone={() => setSaved(true)} />
              ) : (
                <ReadOnlyDetails product={product.data} currency={me?.organization?.base_currency} />
              )}
            </Card>
            <div className="flex flex-col gap-6">
              <ImageCard product={product.data} canManage={canManage} />
              <CodesCard productId={id} canManage={canManage} />
              <PriceHistoryCard productId={id} version={product.data.version} currency={me?.organization?.base_currency} />
            </div>
          </div>
        </>
      )}
    </>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  const headingId = `${title.toLowerCase().replace(/\s+/g, "-")}-heading`;
  return (
    <section aria-labelledby={headingId} className="rounded-lg bg-white p-4 ring-1 ring-slate-200">
      <h2 id={headingId} className="mb-3 text-base font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ReadOnlyDetails({ product, currency }: { product: Product; currency: string | undefined }) {
  return (
    <dl className="grid grid-cols-[8rem_1fr] gap-2 text-sm">
      <dt className="text-slate-600">Price</dt>
      <dd>{formatMoney(product.selling_price, currency)}</dd>
      <dt className="text-slate-600">Tracks stock</dt>
      <dd>{product.track_inventory ? "Yes" : "No"}</dd>
    </dl>
  );
}

// --- Image ------------------------------------------------------------------------------

function ImageCard({ product, canManage }: { product: Product; canManage: boolean }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: PRODUCTS_KEY });
  const upload = useMutation({
    mutationFn: (file: File) =>
      unwrap(
        api.POST("/api/v1/products/{product_id}/image/", {
          params: { path: { product_id: product.id } },
          body: { image: file as unknown as string },
          bodySerializer: (body) => {
            const data = new FormData();
            data.append("image", body?.image as unknown as File);
            return data;
          },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/products/{product_id}/image/", { params: { path: { product_id: product.id } } })),
    onSuccess: refresh,
  });
  const error = upload.error ?? remove.error;
  const message = error instanceof ApiError ? (error.fieldErrors().image ?? null) : null;

  return (
    <Card title="Image">
      {product.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element -- served from the media origin, already resized
        <img src={product.image_url} alt={product.name} className="mb-3 aspect-square w-full rounded object-contain" />
      ) : (
        <p className="mb-3 text-sm text-slate-600">No image yet.</p>
      )}
      {error && (message ? <p className="mb-3 text-sm text-red-700" role="alert">{message}</p> : <ErrorAlert error={error} />)}
      {canManage && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex min-h-11 cursor-pointer items-center rounded-md bg-emerald-700 px-4 text-sm font-medium text-white focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-700 hover:bg-emerald-800">
            {upload.isPending ? "Uploading…" : product.image_url ? "Replace image" : "Upload image"}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="sr-only"
              disabled={upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
                e.target.value = "";
              }}
            />
          </label>
          {product.image_url && (
            <Button variant="secondary" loading={remove.isPending} onClick={() => remove.mutate()}>
              Remove
            </Button>
          )}
          <p className="w-full text-xs text-slate-600">JPEG, PNG or WebP, up to 5 MB.</p>
        </div>
      )}
    </Card>
  );
}

// --- Codes ------------------------------------------------------------------------------

function CodesCard({ productId, canManage }: { productId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const key = [...PRODUCTS_KEY, productId, "identifiers"];
  const codes = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/products/{product_id}/identifiers/", { params: { path: { product_id: productId } } })),
  });
  const [form, setForm] = useState({ value: "", pack_quantity: "1" });
  const refresh = () => queryClient.invalidateQueries({ queryKey: PRODUCTS_KEY });
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/products/{product_id}/identifiers/", { params: { path: { product_id: productId } }, body: form })),
    onSuccess: async () => {
      setForm({ value: "", pack_quantity: "1" });
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (identifierId: string) =>
      unwrap(
        api.DELETE("/api/v1/products/{product_id}/identifiers/{identifier_id}/", {
          params: { path: { product_id: productId, identifier_id: identifierId } },
        }),
      ),
    onSuccess: refresh,
  });
  const errors = add.error instanceof ApiError ? add.error.fieldErrors() : {};

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <Card title="Barcodes and codes">
      {codes.error && <ErrorAlert error={codes.error} />}
      {codes.data && codes.data.length === 0 && <p className="mb-3 text-sm text-slate-600">No codes yet. Products can still be found by name or SKU.</p>}
      {codes.data && codes.data.length > 0 && (
        <ul className="mb-3 divide-y divide-slate-100">
          {codes.data.map((code) => (
            <li key={code.id} className="flex items-center justify-between gap-2 py-2 text-sm">
              <span>
                <span className="font-mono">{code.value}</span>
                {Number(code.pack_quantity) !== 1 && <span className="text-slate-600"> · pack of {Number(code.pack_quantity)}</span>}
                {code.is_primary && <span className="text-slate-600"> · primary</span>}
              </span>
              {canManage && (
                <Button variant="secondary" onClick={() => remove.mutate(code.id)} aria-label={`Remove ${code.value}`}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {remove.error && <ErrorAlert error={remove.error} />}
      {canManage && (
        <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3">
          {add.error && !Object.keys(errors).length && <ErrorAlert error={add.error} />}
          <TextField label="Add a code" inputMode="numeric" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} error={errors.value} hint="Scan or type a barcode." />
          <TextField
            label="Units per scan"
            inputMode="decimal"
            value={form.pack_quantity}
            onChange={(e) => setForm({ ...form, pack_quantity: e.target.value })}
            error={errors.pack_quantity}
            hint="12 for a carton barcode of 12."
          />
          <Button type="submit" variant="secondary" loading={add.isPending}>
            Add code
          </Button>
        </form>
      )}
    </Card>
  );
}

// --- Price history ----------------------------------------------------------------------

function PriceHistoryCard({ productId, version, currency }: { productId: string; version: number; currency: string | undefined }) {
  const history = useQuery({
    // Keyed by version: a saved price change shows up straight away.
    queryKey: [...PRODUCTS_KEY, productId, "price-history", version],
    queryFn: () => unwrap(api.GET("/api/v1/products/{product_id}/price-history/", { params: { path: { product_id: productId } } })),
  });
  return (
    <Card title="Price history">
      {history.error && <ErrorAlert error={history.error} />}
      {history.data && (
        <ol className="divide-y divide-slate-100 text-sm">
          {history.data.results.map((change) => (
            <li key={change.id} className="py-2">
              <span className="tabular-nums">
                {change.old_price === null ? "Started at " : `${formatMoney(change.old_price, currency)} → `}
                {formatMoney(change.new_price, currency)}
              </span>
              <span className="block text-xs text-slate-600">
                {new Date(change.changed_at).toLocaleString("en-KE")}
                {change.changed_by ? ` · ${change.changed_by}` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
