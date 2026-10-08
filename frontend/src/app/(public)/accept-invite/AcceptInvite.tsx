"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert, Loading } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { ME_KEY } from "@/lib/auth";

export function AcceptInvite() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const token = useSearchParams().get("token") ?? "";
  const preview = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => unwrap(api.POST("/api/v1/auth/invitations/preview/", { body: { token } })),
    retry: false,
  });
  // Who (if anyone) is signed in in this browser.
  const me = useQuery({ queryKey: ME_KEY, queryFn: () => unwrap(api.GET("/api/v1/auth/me/")), retry: false });
  const [form, setForm] = useState({ full_name: "", password: "" });

  const accept = useMutation({
    mutationFn: async () => {
      const result = await unwrap(
        api.POST("/api/v1/auth/invitations/accept/", { body: { token, client: "web", ...form } }),
      );
      if (result && "organization_id" in result && result.organization_id) {
        await unwrap(api.POST("/api/v1/auth/switch-organization/", { body: { organization_id: result.organization_id } }));
      }
      queryClient.clear();
    },
    onSuccess: () => router.replace("/"),
  });
  const errors = accept.error instanceof ApiError ? accept.error.fieldErrors() : {};

  if (preview.isPending || me.isPending) return <Loading label="Opening your invitation…" />;
  if (preview.error) return <ErrorAlert error={preview.error} title="This invitation can’t be used" />;

  const invitation = preview.data;
  const signedInAs = me.data?.user.email;
  const heading = (
    <>
      <h1 className="text-xl font-semibold">Join {invitation.organization_name}</h1>
      <p className="text-slate-700">
        You’ve been invited as <strong>{invitation.role_name}</strong> ({invitation.email}).
      </p>
    </>
  );

  if (invitation.account_exists) {
    if (signedInAs !== invitation.email) {
      const next = `/accept-invite?token=${encodeURIComponent(token)}`;
      return (
        <div className="flex flex-col gap-4">
          {heading}
          <p className="text-slate-700">
            {signedInAs ? `You’re signed in as ${signedInAs}. ` : ""}Sign in as {invitation.email} to accept.
          </p>
          <Link href={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-emerald-800 underline">
            Sign in as {invitation.email}
          </Link>
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-4">
        {heading}
        {accept.error && <ErrorAlert error={accept.error} title="Couldn't accept" />}
        <Button onClick={() => accept.mutate()} loading={accept.isPending}>
          Accept invitation
        </Button>
      </div>
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    accept.mutate();
  }
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {heading}
      {accept.error && !Object.keys(errors).length && <ErrorAlert error={accept.error} title="Couldn't accept" />}
      <TextField label="Your name" autoComplete="name" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} error={errors.full_name} />
      <TextField
        label="Choose a password"
        type="password"
        autoComplete="new-password"
        required
        value={form.password}
        onChange={(e) => setForm({ ...form, password: e.target.value })}
        error={errors.password}
        hint="At least 10 characters. Avoid common words."
      />
      <Button type="submit" loading={accept.isPending}>
        Join {invitation.organization_name}
      </Button>
    </form>
  );
}
