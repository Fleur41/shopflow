"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, EmptyState, ErrorAlert, Loading, Notice, PageHeader } from "@/components/ui/Feedback";
import { can, useMe } from "@/lib/auth";
import { TAX_TYPE_LABELS, formatRate } from "@/lib/catalog";
import { useBrands, useCategories, useTaxRates, useUnits } from "@/lib/catalog-queries";

import { BrandForm, CategoryForm, TaxRateForm, UnitForm } from "./LookupForms";

type Entry = { id: string; is_active?: boolean };
type Column<T> = { header: string; cell: (row: T) => ReactNode };

export default function CatalogSetupPage() {
  const { data: me } = useMe();
  const canManage = can(me, "products.manage");
  const categories = useCategories();
  const categoryNames = new Map((categories.data?.results ?? []).map((c) => [c.id, c.name]));

  return (
    <>
      <PageHeader title="Catalog setup" description="The lists your products are organised and taxed with." />
      <div className="flex flex-col gap-10">
        <LookupSection
          title="Categories"
          addLabel="Add category"
          query={categories}
          canManage={canManage}
          columns={[
            { header: "Name", cell: (c) => c.name },
            { header: "Inside", cell: (c) => (c.parent ? categoryNames.get(c.parent) ?? "—" : "Top level") },
          ]}
          form={(entry, onDone) => <CategoryForm entry={entry} onDone={onDone} />}
        />
        <LookupSection
          title="Brands"
          addLabel="Add brand"
          query={useBrands()}
          canManage={canManage}
          columns={[{ header: "Name", cell: (b) => b.name }]}
          form={(entry, onDone) => <BrandForm entry={entry} onDone={onDone} />}
        />
        <LookupSection
          title="Units"
          addLabel="Add unit"
          query={useUnits()}
          canManage={canManage}
          columns={[
            { header: "Code", cell: (u) => <span className="font-mono">{u.code}</span> },
            { header: "Name", cell: (u) => u.name },
            { header: "Fractions", cell: (u) => (u.allows_fraction ? "Allowed" : "—") },
            { header: "KRA unit", cell: (u) => u.etims_quantity_unit || "Not set" },
          ]}
          form={(entry, onDone) => <UnitForm entry={entry} onDone={onDone} />}
        />
        <LookupSection
          title="Tax rates"
          addLabel="Add tax rate"
          query={useTaxRates()}
          canManage={canManage}
          columns={[
            { header: "Name", cell: (t) => t.name },
            { header: "Rate", cell: (t) => formatRate(t.rate) },
            { header: "KRA tax type", cell: (t) => (t.etims_tax_type ? TAX_TYPE_LABELS[t.etims_tax_type] : "Not set") },
          ]}
          form={(entry, onDone) => <TaxRateForm entry={entry} onDone={onDone} />}
        />
      </div>
    </>
  );
}

function LookupSection<T extends Entry & { name: string }>({
  title,
  addLabel,
  query,
  canManage,
  columns,
  form,
}: {
  title: string;
  addLabel: string;
  query: UseQueryResult<{ results: T[]; next?: string | null }>;
  canManage: boolean;
  columns: Column<T>[];
  form: (entry: T | null, onDone: () => void) => ReactNode;
}) {
  // undefined: closed; null: adding; an entry: editing it.
  const [editing, setEditing] = useState<T | null | undefined>(undefined);
  const rows = query.data?.results ?? [];
  const headingId = `${title.toLowerCase().replace(/\s+/g, "-")}-heading`;

  return (
    <section aria-labelledby={headingId}>
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 id={headingId} className="text-lg font-semibold">
          {title}
        </h2>
        {canManage && (
          <Button variant="secondary" onClick={() => setEditing(null)}>
            {addLabel}
          </Button>
        )}
      </div>
      {query.isPending && <Loading label={`Loading ${title.toLowerCase()}…`} />}
      {query.error && <ErrorAlert error={query.error} title={`Couldn't load ${title.toLowerCase()}`} />}
      {query.isSuccess && rows.length === 0 && <EmptyState title={`No ${title.toLowerCase()} yet`} />}
      {query.data?.next && <Notice>Showing the first {rows.length}.</Notice>}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-slate-200">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{title}</caption>
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                {columns.map((column) => (
                  <th key={column.header} scope="col" className="px-4 py-3">
                    {column.header}
                  </th>
                ))}
                <th scope="col" className="px-4 py-3">
                  Status
                </th>
                {canManage && (
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 last:border-0">
                  {columns.map((column) => (
                    <td key={column.header} className="px-4 py-3">
                      {column.cell(row)}
                    </td>
                  ))}
                  <td className="px-4 py-3">{row.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>}</td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      <Button variant="secondary" onClick={() => setEditing(row)} aria-label={`Edit ${row.name}`}>
                        Edit
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={editing !== undefined} onClose={() => setEditing(undefined)} title={editing ? `Edit ${editing.name}` : addLabel}>
        {editing !== undefined && <div key={editing?.id ?? "new"}>{form(editing, () => setEditing(undefined))}</div>}
      </Dialog>
    </section>
  );
}
