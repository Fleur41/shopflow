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
import { INVITATIONS_KEY, MEMBERS_KEY, ROLES_KEY, STORES_KEY } from "@/lib/query-keys";

export default function StaffPage() {
  const { data: me } = useMe();
  const canManage = can(me, "users.manage");
  const [adding, setAdding] = useState(false);
  const [inviting, setInviting] = useState(false);
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
        actions={
          canManage && (
            <>
              <Button variant="secondary" onClick={() => setInviting(true)}>
                Invite by email
              </Button>
              <Button onClick={() => setAdding(true)}>Add staff</Button>
            </>
          )
        }
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
      {canManage && <PendingInvitations />}
      <Dialog open={inviting} onClose={() => setInviting(false)} title="Invite by email">
        <InviteForm onDone={() => setInviting(false)} />
      </Dialog>
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


function PendingInvitations() {
  const queryClient = useQueryClient();
  const invitations = useQuery({ queryKey: INVITATIONS_KEY, queryFn: () => unwrap(api.GET("/api/v1/invitations/")) });
  const revoke = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/invitations/{invitation_id}/revoke/", { params: { path: { invitation_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: INVITATIONS_KEY }),
  });
  const rows = invitations.data?.results ?? [];
  if (invitations.error) return <div className="mt-6"><ErrorAlert error={invitations.error} title="Couldn't load invitations" /></div>;
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="pending-heading" className="mt-8">
      <h2 id="pending-heading" className="mb-3 text-lg font-semibold">
        Pending invitations
      </h2>
      {revoke.error && <ErrorAlert error={revoke.error} />}
      <ul className="flex flex-col gap-2">
        {rows.map((invitation) => (
          <li key={invitation.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-white px-4 py-3 ring-1 ring-slate-200">
            <span>
              <span className="font-medium">{invitation.email}</span>
              <span className="text-slate-600"> · {invitation.role.name}</span>
              {invitation.status === "EXPIRED" && <span className="ml-2"><Badge tone="warning">Expired</Badge></span>}
            </span>
            <Button variant="ghost" loading={revoke.isPending && revoke.variables === invitation.id} onClick={() => revoke.mutate(invitation.id)}>
              Withdraw<span className="sr-only"> invitation for {invitation.email}</span>
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function InviteForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [idempotencyKey] = useState(newIdempotencyKey);
  const roles = useQuery({ queryKey: ROLES_KEY, queryFn: () => unwrap(api.GET("/api/v1/roles/")) });
  const stores = useQuery({ queryKey: [...STORES_KEY, "all"], queryFn: () => unwrap(api.GET("/api/v1/stores/", { params: { query: { page_size: 200 } } })) });
  const [form, setForm] = useState({ email: "", role_id: "", all_stores: false, store_ids: [] as string[] });
  const invite = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/invitations/", {
          body: { ...form, role_id: form.role_id || (roles.data?.results.find((r) => r.template === "CASHIER")?.id ?? "") },
          params: { header: { "Idempotency-Key": idempotencyKey } },
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: INVITATIONS_KEY });
      onDone();
    },
  });
  const errors = invite.error instanceof ApiError ? invite.error.fieldErrors() : {};

  if (roles.isPending || stores.isPending) return <Loading />;
  if (roles.error || stores.error) return <ErrorAlert error={roles.error ?? stores.error} />;
  const assignable = roles.data.results.filter((role) => role.template !== "OWNER");
  const defaultRole = assignable.find((role) => role.template === "CASHIER")?.id ?? "";

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        invite.mutate();
      }}
      noValidate
      className="flex flex-col gap-4"
    >
      <p className="text-slate-700">They’ll get an email link to join, using their existing ShopFlow account or a new one.</p>
      {invite.error && !Object.keys(errors).length && <ErrorAlert error={invite.error} />}
      <TextField label="Email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} error={errors.email} />
      <SelectField label="Role" value={form.role_id || defaultRole} onChange={(e) => setForm({ ...form, role_id: e.target.value })} error={errors.role_id}>
        {assignable.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </SelectField>
      <CheckboxField label="Can work in all stores" checked={form.all_stores} onChange={(e) => setForm({ ...form, all_stores: e.target.checked })} />
      {!form.all_stores && (
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm font-medium">Stores</legend>
          {stores.data.results.map((store) => (
            <CheckboxField
              key={store.id}
              label={`${store.code} · ${store.name}`}
              checked={form.store_ids.includes(store.id)}
              onChange={(e) =>
                setForm({ ...form, store_ids: e.target.checked ? [...form.store_ids, store.id] : form.store_ids.filter((s) => s !== store.id) })
              }
            />
          ))}
          {errors.store_ids && <p className="text-sm font-medium text-red-700">{errors.store_ids}</p>}
        </fieldset>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={invite.isPending}>
          Send invitation
        </Button>
      </div>
    </form>
  );
}
