"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Mail, Phone, Star, Truck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CheckboxField, TextField } from "@/components/ui/Field";
import { Badge, Card, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Supplier } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { PRODUCTS_KEY, SUPPLIERS_KEY } from "@/lib/query-keys";

import { linkTerms } from "../link-terms";
import { SupplierForm, paymentTerms } from "../SupplierForm";

export default function SupplierPage() {
  const { id } = useParams<{ id: string }>();
  const { data: me } = useMe();
  const canManage = can(me, "suppliers.manage");
  const supplier = useQuery({
    queryKey: [...SUPPLIERS_KEY, id],
    queryFn: () => unwrap(api.GET("/api/v1/suppliers/{entry_id}/", { params: { path: { entry_id: id } } })),
  });

  return (
    <>
      <Link href="/suppliers" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" />
        All suppliers
      </Link>
      {supplier.isPending && <Loading label="Loading supplier…" />}
      {supplier.error && <ErrorAlert error={supplier.error} title="Couldn't load this supplier" />}
      {supplier.data && (
        <>
          <SupplierHero supplier={supplier.data} />
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <div className="flex flex-col gap-6">
              <SuppliedProductsCard supplierId={id} canManage={canManage} />
              {canManage && (
                <Card title="Details">
                  <SupplierForm key={supplier.data.version} supplier={supplier.data} onDone={() => undefined} />
                </Card>
              )}
            </div>
            <ContactsCard supplierId={id} canManage={canManage} />
          </div>
        </>
      )}
    </>
  );
}

function SupplierHero({ supplier }: { supplier: Supplier }) {
  return (
    <section aria-labelledby="supplier-title" className="rounded-2xl bg-white p-5 shadow-card ring-1 ring-slate-200 sm:p-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <span aria-hidden="true" className="flex size-14 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/15">
          <Truck className="size-7" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="tabular rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs font-medium text-slate-700">{supplier.code}</span>
            {supplier.kra_pin && (
              <span className="tabular rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs font-medium text-slate-700">KRA {supplier.kra_pin}</span>
            )}
            {!supplier.is_active && <Badge>Inactive</Badge>}
          </div>
          <h1 id="supplier-title" className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">
            {supplier.name}
          </h1>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {supplier.phone && (
              <a href={`tel:${supplier.phone}`} className="tabular inline-flex items-center gap-1.5 text-emerald-800 hover:underline">
                <Phone aria-hidden="true" className="size-4" /> {supplier.phone}
              </a>
            )}
            {supplier.email && (
              <a href={`mailto:${supplier.email}`} className="inline-flex items-center gap-1.5 text-emerald-800 hover:underline">
                <Mail aria-hidden="true" className="size-4" /> {supplier.email}
              </a>
            )}
            {supplier.address && <span className="text-slate-600">{supplier.address}</span>}
          </div>
        </div>
        <div className="sm:text-right">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-600">Payment terms</p>
          <p className="tabular text-2xl font-semibold tracking-tight text-slate-950">{paymentTerms(supplier.payment_terms_days)}</p>
        </div>
      </div>
      {supplier.notes && <p className="mt-4 whitespace-pre-line rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{supplier.notes}</p>}
    </section>
  );
}

// --- Supplied products ---------------------------------------------------------------------

function SuppliedProductsCard({ supplierId, canManage }: { supplierId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const key = [...SUPPLIERS_KEY, supplierId, "products"];
  const links = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/suppliers/{supplier_id}/products/", { params: { path: { supplier_id: supplierId }, query: { page_size: 200 } } })),
  });
  const refresh = () =>
    Promise.all([queryClient.invalidateQueries({ queryKey: SUPPLIERS_KEY }), queryClient.invalidateQueries({ queryKey: PRODUCTS_KEY })]);
  const remove = useMutation({
    mutationFn: (linkId: string) => unwrap(api.DELETE("/api/v1/product-suppliers/{link_id}/", { params: { path: { link_id: linkId } } })),
    onSuccess: refresh,
  });
  const rows = links.data?.results ?? [];
  const linked = new Set(rows.map((link) => link.product));

  return (
    <Card title="Products supplied" description="What you can order from them, and on what terms.">
      {links.error && <ErrorAlert error={links.error} />}
      {links.isSuccess && rows.length === 0 && <p className="mb-4 text-sm text-slate-600">No products linked yet.</p>}
      {rows.length > 0 && (
        <ul className="mb-4 divide-y divide-slate-100">
          {rows.map((link) => (
            <li key={link.id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <Link href={`/products/${link.product}`} className="font-medium text-slate-900 hover:text-emerald-800 hover:underline">
                  {link.product_name}
                </Link>
                {link.is_preferred && (
                  <span className="ml-2 inline-flex items-center gap-1 text-xs font-semibold text-amber-800">
                    <Star aria-hidden="true" className="size-3.5 fill-amber-400 text-amber-500" /> Preferred
                  </span>
                )}
                <p className="tabular text-xs text-slate-600">{linkTerms(link) || <span className="font-mono">{link.product_sku}</span>}</p>
              </div>
              {canManage && (
                <Button variant="secondary" onClick={() => remove.mutate(link.id)} aria-label={`Unlink ${link.product_name}`}>
                  Unlink
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {remove.error && <ErrorAlert error={remove.error} />}
      {canManage && <LinkProductForm supplierId={supplierId} alreadyLinked={linked} onLinked={refresh} />}
    </Card>
  );
}

/** Find a product by name, SKU or barcode, then link it with the supplier's terms. */
function LinkProductForm({ supplierId, alreadyLinked, onLinked }: { supplierId: string; alreadyLinked: Set<string>; onLinked: () => Promise<unknown> }) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<{ id: string; name: string } | null>(null);
  const [terms, setTerms] = useState({ supplier_sku: "", min_order_qty: "", lead_time_days: "", is_preferred: false });
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const results = useQuery({
    queryKey: [...PRODUCTS_KEY, "pick", query],
    queryFn: () => unwrap(api.GET("/api/v1/products/", { params: { query: { search: query, is_active: true, page_size: 6 } } })),
    enabled: query.length > 0 && !chosen,
  });
  const link = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/suppliers/{supplier_id}/products/", {
          params: { path: { supplier_id: supplierId } },
          body: {
            product: chosen!.id,
            supplier_sku: terms.supplier_sku,
            min_order_qty: terms.min_order_qty || null,
            lead_time_days: terms.lead_time_days ? Number(terms.lead_time_days) : null,
            is_preferred: terms.is_preferred,
          },
        }),
      ),
    onSuccess: async () => {
      setChosen(null);
      setSearch("");
      setTerms({ supplier_sku: "", min_order_qty: "", lead_time_days: "", is_preferred: false });
      await onLinked();
    },
  });
  const errors = link.error instanceof ApiError ? link.error.fieldErrors() : {};

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (chosen) link.mutate();
  }

  if (!chosen) {
    const options = (results.data?.results ?? []).filter((p) => !alreadyLinked.has(p.id));
    return (
      <div className="flex flex-col gap-2 border-t border-slate-100 pt-4">
        <TextField label="Link a product" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name, SKU or barcode" />
        {query && results.isSuccess && options.length === 0 && <p className="text-sm text-slate-600">No unlinked products match “{query}”.</p>}
        {options.length > 0 && (
          <ul aria-label="Matching products" className="flex flex-col gap-1">
            {options.map((product) => (
              <li key={product.id}>
                <button
                  type="button"
                  onClick={() => setChosen({ id: product.id, name: product.name })}
                  className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-3 text-left text-sm ring-1 ring-slate-200 hover:bg-emerald-50 hover:ring-emerald-600/30"
                >
                  <span className="font-medium">{product.name}</span>
                  <span className="tabular font-mono text-xs text-slate-600">{product.sku}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3 border-t border-slate-100 pt-4">
      <p className="text-sm">
        Linking <span className="font-semibold">{chosen.name}</span>
      </p>
      {link.error && !Object.keys(errors).length && <ErrorAlert error={link.error} />}
      {errors.supplier && <p role="alert" className="text-sm font-medium text-red-700">{errors.supplier}</p>}
      <div className="grid gap-3 sm:grid-cols-3">
        <TextField label="Their code" value={terms.supplier_sku} onChange={(e) => setTerms({ ...terms, supplier_sku: e.target.value })} error={errors.supplier_sku} />
        <TextField label="Minimum order" inputMode="decimal" value={terms.min_order_qty} onChange={(e) => setTerms({ ...terms, min_order_qty: e.target.value })} error={errors.min_order_qty} />
        <TextField label="Lead time (days)" inputMode="numeric" value={terms.lead_time_days} onChange={(e) => setTerms({ ...terms, lead_time_days: e.target.value })} error={errors.lead_time_days} />
      </div>
      <CheckboxField label="Preferred supplier for this product" checked={terms.is_preferred} onChange={(e) => setTerms({ ...terms, is_preferred: e.target.checked })} />
      <div className="flex gap-2">
        <Button type="submit" loading={link.isPending}>
          Link product
        </Button>
        <Button variant="secondary" onClick={() => setChosen(null)}>
          Choose another
        </Button>
      </div>
    </form>
  );
}

// --- Contacts ---------------------------------------------------------------------------

function ContactsCard({ supplierId, canManage }: { supplierId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const key = [...SUPPLIERS_KEY, supplierId, "contacts"];
  const contacts = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/suppliers/{supplier_id}/contacts/", { params: { path: { supplier_id: supplierId } } })),
  });
  const [form, setForm] = useState({ name: "", role_title: "", phone: "", email: "" });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/suppliers/{supplier_id}/contacts/", { params: { path: { supplier_id: supplierId } }, body: form })),
    onSuccess: async () => {
      setForm({ name: "", role_title: "", phone: "", email: "" });
      await refresh();
    },
  });
  const makePrimary = useMutation({
    mutationFn: (contactId: string) =>
      unwrap(
        api.PATCH("/api/v1/suppliers/{supplier_id}/contacts/{contact_id}/", {
          params: { path: { supplier_id: supplierId, contact_id: contactId } },
          body: { is_primary: true },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (contactId: string) =>
      unwrap(api.DELETE("/api/v1/suppliers/{supplier_id}/contacts/{contact_id}/", { params: { path: { supplier_id: supplierId, contact_id: contactId } } })),
    onSuccess: refresh,
  });
  const errors = add.error instanceof ApiError ? add.error.fieldErrors() : {};

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <Card title="Contacts" description="The people you deal with.">
      {contacts.error && <ErrorAlert error={contacts.error} />}
      {contacts.data && contacts.data.length === 0 && <p className="mb-4 text-sm text-slate-600">No contacts yet.</p>}
      {contacts.data && contacts.data.length > 0 && (
        <ul className="mb-4 flex flex-col gap-3">
          {contacts.data.map((contact) => (
            <li key={contact.id} className="rounded-lg p-3 ring-1 ring-slate-200">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium">
                    {contact.name}
                    {contact.is_primary && <Badge tone="success">Primary</Badge>}
                  </p>
                  {contact.role_title && <p className="text-sm text-slate-600">{contact.role_title}</p>}
                  <div className="mt-1 flex flex-col text-sm">
                    {contact.phone && (
                      <a href={`tel:${contact.phone}`} className="tabular text-emerald-800 hover:underline">
                        {contact.phone}
                      </a>
                    )}
                    {contact.email && (
                      <a href={`mailto:${contact.email}`} className="truncate text-emerald-800 hover:underline">
                        {contact.email}
                      </a>
                    )}
                  </div>
                </div>
              </div>
              {canManage && (
                <div className="mt-2 flex gap-2">
                  {!contact.is_primary && (
                    <Button variant="ghost" className="min-h-9 px-2" onClick={() => makePrimary.mutate(contact.id)} aria-label={`Make ${contact.name} the primary contact`}>
                      Make primary
                    </Button>
                  )}
                  <Button variant="ghost" className="min-h-9 px-2" onClick={() => remove.mutate(contact.id)} aria-label={`Remove ${contact.name}`}>
                    Remove
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3 border-t border-slate-100 pt-4">
          {add.error && !Object.keys(errors).length && <ErrorAlert error={add.error} />}
          <TextField label="Contact name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} />
          <TextField label="Role" value={form.role_title} onChange={(e) => setForm({ ...form, role_title: e.target.value })} error={errors.role_title} placeholder="e.g. Sales rep" />
          <TextField label="Contact phone" type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} error={errors.phone} />
          <TextField label="Contact email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} error={errors.email} />
          <Button type="submit" variant="secondary" loading={add.isPending}>
            Add contact
          </Button>
        </form>
      )}
    </Card>
  );
}
