"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { CheckboxField, SelectField, TextField } from "@/components/ui/Field";
import { Badge, EmptyState, ErrorAlert, Loading, PageHeader } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Member } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { MEMBERS_KEY, ROLES_KEY, STORES_KEY } from "@/lib/query-keys";

export default function StaffPage() {
  const { data: me } = useMe();
  const canManage = can(me, "users.manage");
  const [adding, setAdding] = useState(false);
  const [suspending, setSuspending] = useState<Member | null>(null);
  const members = useQuery({
    queryKey: MEMBERS_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/members/", { params: { query: { page_size: 200 } } })),
  });
  const rows = members.data?.results ?? [];

  return (
    <>
      <PageHeader
        title="Staff"
        description="People who can sign in to this business, their role and which stores they work in."
        actions={canManage && <Button onClick={() => setAdding(true)}>Add staff</Button>}
      />
      {members.isPending && <Loading label="Loading staff…" />}
      {members.error && <ErrorAlert error={members.error} title="Couldn't load staff" />}
      {members.isSuccess && rows.length === 0 && <EmptyState title="No staff yet" />}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-slate-200">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Staff members</caption>
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th scope="col" className="px-4 py-3">Name</th>
                <th scope="col" className="px-4 py-3">Role</th>
                <th scope="col" className="px-4 py-3">Stores</th>
                <th scope="col" className="px-4 py-3">Status</th>
                {canManage && (
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((member) => (
                <tr key={member.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-medium">{member.user.full_name}</div>
                    <div className="text-slate-600">{member.user.email}</div>
                  </td>
                  <td className="px-4 py-3">{member.role.name}</td>
                  <td className="px-4 py-3">{member.all_stores ? "All stores" : member.stores.map((s) => s.code).join(", ")}</td>
                  <td className="px-4 py-3">
                    {member.status === "ACTIVE" ? <Badge tone="success">Active</Badge> : <Badge tone="warning">Suspended</Badge>}
                  </td>
                  {canManage && (
                    <td className="px-4 py-3 text-right">
                      {member.user.id !== me?.user.id &&
                        (member.status === "ACTIVE" ? (
                          <Button variant="ghost" onClick={() => setSuspending(member)}>
                            Suspend<span className="sr-only"> {member.user.full_name}</span>
                          </Button>
                        ) : (
                          <ReactivateButton member={member} />
                        ))}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Add staff">
        <AddStaffForm onDone={() => setAdding(false)} />
      </Dialog>
      <Dialog open={suspending !== null} onClose={() => setSuspending(null)} title={`Suspend ${suspending?.user.full_name ?? ""}`}>
        {suspending && <SuspendForm member={suspending} onDone={() => setSuspending(null)} />}
      </Dialog>
    </>
  );
}

function useInvalidateMembers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: MEMBERS_KEY });
}

function AddStaffForm({ onDone }: { onDone: () => void }) {
  const invalidate = useInvalidateMembers();
  const [idempotencyKey] = useState(newIdempotencyKey);
  const roles = useQuery({ queryKey: ROLES_KEY, queryFn: () => unwrap(api.GET("/api/v1/roles/")) });
  const stores = useQuery({ queryKey: [...STORES_KEY, "all"], queryFn: () => unwrap(api.GET("/api/v1/stores/", { params: { query: { page_size: 200 } } })) });
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role_id: "", all_stores: false, store_ids: [] as string[] });
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/members/", {
          body: { ...form, role_id: form.role_id || (roles.data?.results.find((r) => r.template === "CASHIER")?.id ?? "") },
          params: { header: { "Idempotency-Key": idempotencyKey } },
        }),
      ),
    onSuccess: async () => {
      await invalidate();
      onDone();
    },
  });
  const errors = create.error instanceof ApiError ? create.error.fieldErrors() : {};
  const set = (field: "full_name" | "email" | "password" | "role_id") => (e: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: e.target.value }));
  const toggleStore = (id: string, checked: boolean) =>
    setForm((current) => ({ ...current, store_ids: checked ? [...current.store_ids, id] : current.store_ids.filter((s) => s !== id) }));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  if (roles.isPending || stores.isPending) return <Loading />;
  if (roles.error || stores.error) return <ErrorAlert error={roles.error ?? stores.error} />;
  const assignable = roles.data.results.filter((role) => role.template !== "OWNER");
  const defaultRole = assignable.find((role) => role.template === "CASHIER")?.id ?? "";

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {create.error && !Object.keys(errors).length && <ErrorAlert error={create.error} />}
      <TextField label="Full name" required value={form.full_name} onChange={set("full_name")} error={errors.full_name} />
      <TextField label="Email" type="email" required value={form.email} onChange={set("email")} error={errors.email} />
      <TextField
        label="Initial password"
        type="password"
        autoComplete="new-password"
        required
        value={form.password}
        onChange={set("password")}
        error={errors.password}
        hint="Share it with them privately. At least 10 characters."
      />
      <SelectField label="Role" value={form.role_id || defaultRole} onChange={set("role_id")} error={errors.role_id}>
        {assignable.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </SelectField>
      <CheckboxField
        label="Can work in all stores"
        checked={form.all_stores}
        onChange={(e) => setForm((current) => ({ ...current, all_stores: e.target.checked }))}
      />
      {!form.all_stores && (
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm font-medium">Stores</legend>
          {stores.data.results.map((store) => (
            <CheckboxField
              key={store.id}
              label={`${store.code} · ${store.name}`}
              checked={form.store_ids.includes(store.id)}
              onChange={(e) => toggleStore(store.id, e.target.checked)}
            />
          ))}
          {errors.store_ids && <p className="text-sm font-medium text-red-700">{errors.store_ids}</p>}
        </fieldset>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={create.isPending}>
          Add staff
        </Button>
      </div>
    </form>
  );
}

function SuspendForm({ member, onDone }: { member: Member; onDone: () => void }) {
  const invalidate = useInvalidateMembers();
  const [reason, setReason] = useState("");
  const suspend = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/members/{member_id}/suspend/", { params: { path: { member_id: member.id } }, body: { reason } })),
    onSuccess: async () => {
      await invalidate();
      onDone();
    },
  });
  const errors = suspend.error instanceof ApiError ? suspend.error.fieldErrors() : {};

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        suspend.mutate();
      }}
      noValidate
      className="flex flex-col gap-4"
    >
      <p className="text-slate-700">They will be signed out of this business immediately.</p>
      {suspend.error && !Object.keys(errors).length && <ErrorAlert error={suspend.error} />}
      <TextField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} hint="Recorded in the audit log." />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="danger" loading={suspend.isPending}>
          Suspend
        </Button>
      </div>
    </form>
  );
}

function ReactivateButton({ member }: { member: Member }) {
  const invalidate = useInvalidateMembers();
  const reactivate = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/members/{member_id}/reactivate/", { params: { path: { member_id: member.id } } })),
    onSuccess: invalidate,
  });
  return (
    <Button variant="ghost" loading={reactivate.isPending} onClick={() => reactivate.mutate()}>
      Reactivate<span className="sr-only"> {member.user.full_name}</span>
    </Button>
  );
}
