"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ImagePlus, Package, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/Button";
import { SelectField, TextField } from "@/components/ui/Field";
import { Badge, Card, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { Money, PriceChange } from "@/components/ui/Money";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Product } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { PRODUCT_TYPE_LABELS } from "@/lib/catalog";
import { useTaxRates, useUnits } from "@/lib/catalog-queries";
import { PRODUCTS_KEY, SUPPLIERS_KEY } from "@/lib/query-keys";

import { linkTerms } from "../../suppliers/link-terms";

import { ProductForm } from "../ProductForm";

export default function ProductPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const currency = me?.organization?.base_currency;
  const canManage = can(me, "products.manage");
  const [saved, setSaved] = useState(false);
  const product = useQuery({
    queryKey: [...PRODUCTS_KEY, id],
    queryFn: () => unwrap(api.GET("/api/v1/products/{entry_id}/", { params: { path: { entry_id: id } } })),
  });

  return (
    <>
      <Link href="/products" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" />
        All products
      </Link>
      {product.isPending && <Loading label="Loading product…" />}
      {product.error && <ErrorAlert error={product.error} title="Couldn't load this product" />}
      {product.data && (
        <>
          <ProductHero product={product.data} currency={currency} />
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card title="Details" description={canManage ? "Changes are saved together and recorded in the audit log." : undefined}>
              <p role="status" className="sr-only">
                {saved ? "Changes saved." : ""}
              </p>
              {canManage ? (
                <ProductForm key={product.data.version} product={product.data} onDone={() => setSaved(true)} />
              ) : (
                <ReadOnlyDetails product={product.data} />
              )}
            </Card>
            <div className="flex flex-col gap-6">
              <PriceHistoryCard productId={id} version={product.data.version} currency={currency} />
              {can(me, "suppliers.view") && <SuppliersCard productId={id} canManage={can(me, "suppliers.manage")} />}
              <ImageCard product={product.data} canManage={canManage} />
              <CodesCard productId={id} canManage={canManage} />
            </div>
          </div>
        </>
      )}
    </>
  );
}

function usePriceHistory(productId: string, version: number) {
  return useQuery({
    // Keyed by version: a saved price change shows up straight away.
    queryKey: [...PRODUCTS_KEY, productId, "price-history", version],
    queryFn: () => unwrap(api.GET("/api/v1/products/{product_id}/price-history/", { params: { path: { product_id: productId } } })),
  });
}

/** The product at a glance: photo, name, codes and, above all, its price. */
function ProductHero({ product, currency }: { product: Product; currency: string | undefined }) {
  const units = useUnits();
  const taxRates = useTaxRates();
  const history = usePriceHistory(product.id, product.version);
  const unit = units.data?.results.find((u) => u.id === product.unit);
  const taxRate = taxRates.data?.results.find((t) => t.id === product.tax_rate);
  const latest = history.data?.results[0];

  return (
    <section aria-labelledby="product-title" className="overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-slate-200">
      <div className="flex flex-col gap-6 p-5 sm:flex-row sm:items-center sm:p-6">
        {product.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- served from the media origin, already resized
          <img src={product.image_url} alt={product.name} className="size-28 shrink-0 rounded-xl object-cover ring-1 ring-slate-200 sm:size-32" />
        ) : (
          <span aria-hidden="true" className="flex size-28 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-500 ring-1 ring-slate-200 sm:size-32">
            <Package className="size-10" />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="tabular rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs font-medium text-slate-700">{product.sku}</span>
            {!product.is_active && <Badge>Inactive</Badge>}
            {unit && <Chip>{unit.name}</Chip>}
            {taxRate && <Chip>{taxRate.name}</Chip>}
            {!product.track_inventory && <Chip>No stock tracking</Chip>}
          </div>
          <h1 id="product-title" className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">
            {product.name}
          </h1>
        </div>
        <div className="sm:text-right">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-600">Selling price</p>
          <Money amount={product.selling_price} currency={currency} size="display" className="text-slate-950" />
          {latest && latest.old_price !== null && latest.old_price !== undefined && (
            <div className="mt-1.5">
              <PriceChange from={latest.old_price} to={latest.new_price} currency={currency} />
              <span className="ml-2 text-xs text-slate-600">last change</span>
            </div>
          )}
        </div>
      </div>
      {product.default_cost && (
        <div className="flex flex-wrap gap-x-8 gap-y-2 border-t border-slate-100 bg-slate-50/70 px-5 py-3 text-sm sm:px-6">
          <span className="text-slate-600">
            Cost <Money amount={product.default_cost} currency={currency} size="sm" className="ml-1 text-slate-900" />
          </span>
          <Margin price={product.selling_price} cost={product.default_cost} />
        </div>
      )}
    </section>
  );
}

/** Gross margin on the selling price, computed exactly (no floats). */
function Margin({ price, cost }: { price: string; cost: string }) {
  const scale = (value: string) => {
    const [whole = "0", fraction = ""] = value.split(".");
    return BigInt(whole + fraction.padEnd(4, "0").slice(0, 4));
  };
  const p = scale(price);
  if (p === 0n) return null;
  const tenths = (2n * (p - scale(cost)) * 1000n + p) / (2n * p); // half up, in 0.1 %
  const negative = tenths < 0n;
  const abs = negative ? -tenths : tenths;
  return (
    <span className="text-slate-600">
      Margin{" "}
      <span className={`tabular font-semibold ${negative ? "text-rose-700" : "text-slate-900"}`}>
        {negative ? "−" : ""}
        {`${abs / 10n}.${abs % 10n}`}%
      </span>
    </span>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-900 ring-1 ring-inset ring-emerald-600/15">{children}</span>;
}

function ReadOnlyDetails({ product }: { product: Product }) {
  return (
    <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-3 text-sm">
      <dt className="text-slate-600">Kind</dt>
      <dd>{PRODUCT_TYPE_LABELS[product.etims_product_type ?? "2"]}</dd>
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
        <img src={product.image_url} alt="" className="mb-4 aspect-square w-full rounded-xl bg-slate-50 object-contain ring-1 ring-slate-200" />
      ) : (
        <p className="mb-3 text-sm text-slate-600">No image yet.</p>
      )}
      {error && (message ? <p className="mb-3 text-sm text-red-700" role="alert">{message}</p> : <ErrorAlert error={error} />)}
      {canManage && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex min-h-11 cursor-pointer items-center rounded-lg bg-emerald-700 shadow-sm px-4 text-sm font-medium text-white focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-700 hover:bg-emerald-800">
            <ImagePlus aria-hidden="true" className="mr-2 size-4" />
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
              <Trash2 aria-hidden="true" className="size-4" />
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
  const history = usePriceHistory(productId, version);
  return (
    <Card title="Price history" description="Every change, with who made it.">
      {history.error && <ErrorAlert error={history.error} />}
      {history.data && (
        <ol className="relative flex flex-col gap-4 border-l border-slate-200 pl-5">
          {history.data.results.map((change) => (
            <li key={change.id} className="relative">
              <span aria-hidden className="absolute -left-[1.6875rem] top-1.5 size-2.5 rounded-full bg-emerald-600 ring-4 ring-white" />
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                {change.old_price !== null && change.old_price !== undefined && (
                  <>
                    <Money amount={change.old_price} currency={currency} size="sm" className="text-slate-600 line-through decoration-slate-400" />
                    <span aria-hidden="true" className="text-slate-500">
                      →
                    </span>
                    <span className="sr-only">to</span>
                  </>
                )}
                <Money amount={change.new_price} currency={currency} size="sm" className="text-slate-950" />
                <PriceChange from={change.old_price} to={change.new_price} currency={currency} />
              </div>
              <p className="tabular mt-0.5 text-xs text-slate-600">
                {new Date(change.changed_at).toLocaleString("en-KE", { dateStyle: "medium", timeStyle: "short" })}
                {change.changed_by ? ` · ${change.changed_by}` : ""}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

// --- Suppliers --------------------------------------------------------------------------

function SuppliersCard({ productId, canManage }: { productId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const links = useQuery({
    queryKey: [...PRODUCTS_KEY, productId, "suppliers"],
    queryFn: () => unwrap(api.GET("/api/v1/products/{product_id}/suppliers/", { params: { path: { product_id: productId } } })),
  });
  const suppliers = useQuery({
    queryKey: [...SUPPLIERS_KEY, "active"],
    queryFn: () => unwrap(api.GET("/api/v1/suppliers/", { params: { query: { is_active: true, page_size: 200 } } })),
    enabled: canManage,
  });
  const [supplierId, setSupplierId] = useState("");
  const refresh = () =>
    Promise.all([queryClient.invalidateQueries({ queryKey: PRODUCTS_KEY }), queryClient.invalidateQueries({ queryKey: SUPPLIERS_KEY })]);
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/products/{product_id}/suppliers/", { params: { path: { product_id: productId } }, body: { supplier: supplierId } })),
    onSuccess: async () => {
      setSupplierId("");
      await refresh();
    },
  });
  const prefer = useMutation({
    mutationFn: (linkId: string) => unwrap(api.PATCH("/api/v1/product-suppliers/{link_id}/", { params: { path: { link_id: linkId } }, body: { is_preferred: true } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (linkId: string) => unwrap(api.DELETE("/api/v1/product-suppliers/{link_id}/", { params: { path: { link_id: linkId } } })),
    onSuccess: refresh,
  });
  const rows = links.data ?? [];
  const linked = new Set(rows.map((link) => link.supplier));
  const choices = (suppliers.data?.results ?? []).filter((supplier) => !linked.has(supplier.id));
  const error = add.error ?? prefer.error ?? remove.error;

  return (
    <Card title="Suppliers" description="Where this product comes from. The preferred one is suggested when reordering.">
      {links.error && <ErrorAlert error={links.error} />}
      {links.isSuccess && rows.length === 0 && <p className="mb-3 text-sm text-slate-600">No suppliers linked yet.</p>}
      {rows.length > 0 && (
        <ul className="mb-3 divide-y divide-slate-100">
          {rows.map((link) => (
            <li key={link.id} className="py-2.5">
              <div className="flex items-center justify-between gap-2">
                <Link href={`/suppliers/${link.supplier}`} className="min-w-0 truncate font-medium text-slate-900 hover:text-emerald-800 hover:underline">
                  {link.supplier_name}
                </Link>
                {link.is_preferred ? (
                  <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-amber-800">
                    <Star aria-hidden="true" className="size-3.5 fill-amber-400 text-amber-500" /> Preferred
                  </span>
                ) : (
                  canManage && (
                    <Button variant="ghost" className="min-h-9 shrink-0 px-2 text-xs" onClick={() => prefer.mutate(link.id)} aria-label={`Prefer ${link.supplier_name}`}>
                      Make preferred
                    </Button>
                  )
                )}
              </div>
              <div className="flex items-center justify-between gap-2">
                <p className="tabular text-xs text-slate-600">{linkTerms(link) || "No order terms yet"}</p>
                {canManage && (
                  <Button variant="ghost" className="min-h-9 shrink-0 px-2 text-xs" onClick={() => remove.mutate(link.id)} aria-label={`Unlink ${link.supplier_name}`}>
                    Unlink
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {error && <ErrorAlert error={error} />}
      {canManage && choices.length > 0 && (
        <div className="flex items-end gap-2 border-t border-slate-100 pt-3">
          <div className="min-w-0 flex-1">
            <SelectField label="Add a supplier" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Choose…</option>
              {choices.map((supplier) => (
                <option key={supplier.id} value={supplier.id}>
                  {supplier.name}
                </option>
              ))}
            </SelectField>
          </div>
          <Button variant="secondary" disabled={!supplierId} loading={add.isPending} onClick={() => add.mutate()}>
            Link
          </Button>
        </div>
      )}
      {canManage && suppliers.isSuccess && suppliers.data.results.length === 0 && (
        <p className="text-sm text-slate-600">
          <Link href="/suppliers" className="font-medium text-emerald-800 underline">
            Add a supplier
          </Link>{" "}
          first, then link it here.
        </p>
      )}
    </Card>
  );
}
