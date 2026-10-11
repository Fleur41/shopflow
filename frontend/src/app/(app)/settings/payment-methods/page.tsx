"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { PaymentMethod } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { cursorFrom } from "@/lib/lists";
import { ETIMS_LABELS, KIND_LABELS } from "@/lib/payment-methods";
import { PAYMENT_METHODS_KEY } from "@/lib/query-keys";

import { AddPaymentMethodForm, EditPaymentMethodForm } from "./PaymentMethodForms";

export default function PaymentMethodsPage() {
  const { data: me } = useMe();
  const canManage = can(me, "org.manage");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<PaymentMethod | null>(null);
  const methods = useInfiniteQuery({
    queryKey: PAYMENT_METHODS_KEY,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/payment-methods/", { params: { query: { cursor: pageParam } } })),
    getNextPageParam: (page) => cursorFrom(page.next),
  });
  const rows = methods.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <PageHeader
        title="Payment methods"
        description="How customers can pay, in the order the buttons appear at the till. Selling on credit is set per customer, not here."
        actions={canManage && <Button onClick={() => setAdding(true)}>Add payment method</Button>}
      />
      {methods.isPending && <Loading label="Loading payment methods…" />}
      {methods.error && <ErrorAlert error={methods.error} title="Couldn't load payment methods" />}
      {methods.isSuccess && rows.length === 0 && <EmptyState title="No payment methods yet" />}
      {rows.length > 0 && (
        <div className="table-card">
          <table>
            <caption className="sr-only">Payment methods</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Code</th>
                <th scope="col">Kind</th>
                <th scope="col">Reference</th>
                <th scope="col">eTIMS type</th>
                <th scope="col">Status</th>
                {canManage && (
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((method) => (
                <tr key={method.id}>
                  <td className="font-medium">{method.name}</td>
                  <td className="font-mono">{method.code}</td>
                  <td>{KIND_LABELS[method.kind]}</td>
                  <td>{method.requires_reference ? "Required" : "—"}</td>
                  <td>{method.etims_payment_type ? ETIMS_LABELS[method.etims_payment_type] : "—"}</td>
                  <td>
                    {method.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>}
                  </td>
                  {canManage && (
                    <td className="text-right">
                      <Button variant="secondary" onClick={() => setEditing(method)} aria-label={`Edit ${method.name}`}>
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
      {methods.hasNextPage && (
        <Button variant="secondary" className="mt-4" loading={methods.isFetchingNextPage} onClick={() => methods.fetchNextPage()}>
          Load more
        </Button>
      )}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add a payment method">
        <AddPaymentMethodForm onDone={() => setAdding(false)} />
      </Dialog>
      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={`Edit ${editing?.name ?? ""}`}>
        {editing && <EditPaymentMethodForm key={editing.id} method={editing} onDone={() => setEditing(null)} />}
      </Dialog>
    </>
  );
}
