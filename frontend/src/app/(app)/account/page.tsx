"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { Badge, ErrorAlert, PageHeader } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { ME_KEY, useMe } from "@/lib/auth";

export default function AccountPage() {
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <>
      <PageHeader title="Your account" description={`${me.user.full_name} · ${me.user.email}`} />
      <div className="flex max-w-2xl flex-col gap-6">
        <EmailSection verified={me.user.email_verified} />
        <TwoStepSection enabled={me.user.mfa_enabled} />
        <PasswordSection />
      </div>
    </>
  );
}

function Section({ title, badge, children }: { title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  const id = title.toLowerCase().replace(/\W+/g, "-");
  return (
    <section aria-labelledby={id} className="rounded-lg bg-white p-5 ring-1 ring-slate-200">
      <div className="mb-3 flex items-center gap-2">
        <h2 id={id} className="text-lg font-semibold">
          {title}
        </h2>
        {badge}
      </div>
      {children}
    </section>
  );
}

function EmailSection({ verified }: { verified: boolean }) {
  const resend = useMutation({ mutationFn: () => unwrap(api.POST("/api/v1/auth/email/verification/")) });
  return (
    <Section title="Email address" badge={verified ? <Badge tone="success">Confirmed</Badge> : <Badge tone="warning">Not confirmed</Badge>}>
      {verified ? (
        <p className="text-slate-700">Your email address is confirmed.</p>
      ) : (
        <div className="flex flex-col items-start gap-3">
          <p className="text-slate-700">Confirm your email so you can always reset your password.</p>
          {resend.isSuccess && <p role="status">We’ve sent a new confirmation link.</p>}
          {resend.error && <ErrorAlert error={resend.error} />}
          <Button variant="secondary" onClick={() => resend.mutate()} loading={resend.isPending}>
            Send confirmation email
          </Button>
        </div>
      )}
    </Section>
  );
}

function TwoStepSection({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ME_KEY });
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const setup = useMutation({ mutationFn: () => unwrap(api.POST("/api/v1/auth/mfa/totp/setup/")) });
  const [code, setCode] = useState("");
  const confirm = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/mfa/totp/confirm/", { body: { code } })),
    onSuccess: async (result) => {
      setRecoveryCodes(result.recovery_codes);
      await refresh();
    },
  });

  if (recoveryCodes) {
    return (
      <Section title="Two-step verification" badge={<Badge tone="success">On</Badge>}>
        <div role="status" className="flex flex-col gap-3">
          <p className="font-semibold">Save your recovery codes</p>
          <p className="text-slate-700">
            If you lose your phone, each code lets you sign in once. They won’t be shown again: write them down or store them
            somewhere safe.
          </p>
          <ul aria-label="Recovery codes" className="grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-3 font-mono sm:grid-cols-3">
            {recoveryCodes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <Button variant="secondary" onClick={() => setRecoveryCodes(null)}>
            I’ve saved them
          </Button>
        </div>
      </Section>
    );
  }

  if (enabled) {
    return (
      <Section title="Two-step verification" badge={<Badge tone="success">On</Badge>}>
        <p className="mb-4 text-slate-700">Signing in needs your password and a code from your authenticator app.</p>
        <DisableTwoStep onDone={refresh} />
      </Section>
    );
  }

  function onConfirm(event: FormEvent) {
    event.preventDefault();
    confirm.mutate();
  }

  return (
    <Section title="Two-step verification" badge={<Badge tone="warning">Off</Badge>}>
      {!setup.data ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-slate-700">
            Protect your business with a code from an authenticator app (such as Google Authenticator or Microsoft
            Authenticator). It’s required to manage staff, stores, prices and other sensitive settings.
          </p>
          {setup.error && <ErrorAlert error={setup.error} />}
          <Button onClick={() => setup.mutate()} loading={setup.isPending}>
            Set up two-step verification
          </Button>
        </div>
      ) : (
        <form onSubmit={onConfirm} noValidate className="flex flex-col gap-4">
          <p className="text-slate-700">1. Scan this QR code with your authenticator app.</p>
          {/* eslint-disable-next-line @next/next/no-img-element -- data: URI from our API, allowed by the CSP */}
          <img src={setup.data.qr_code} alt="QR code for your authenticator app" width={180} height={180} className="rounded-md ring-1 ring-slate-200" />
          <p className="text-sm text-slate-700">
            Can’t scan? Enter this key instead: <code data-testid="totp-secret" className="break-all rounded bg-slate-100 px-1 font-mono">{setup.data.secret}</code>
          </p>
          <p className="text-slate-700">2. Enter the 6-digit code the app shows.</p>
          {confirm.error && !(confirm.error instanceof ApiError && Object.keys(confirm.error.fieldErrors()).length) && (
            <ErrorAlert error={confirm.error} title="Code not accepted" />
          )}
          <TextField
            label="Verification code"
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" loading={confirm.isPending}>
            Turn on two-step verification
          </Button>
        </form>
      )}
    </Section>
  );
}

function DisableTwoStep({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ password: "", code: "" });
  const disable = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/mfa/totp/disable/", { body: form })),
    onSuccess: onDone,
  });
  const errors = disable.error instanceof ApiError ? disable.error.fieldErrors() : {};
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium text-red-800">Turn off two-step verification</summary>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          disable.mutate();
        }}
        noValidate
        className="mt-3 flex flex-col gap-4"
      >
        {disable.error && !Object.keys(errors).length && <ErrorAlert error={disable.error} />}
        <TextField label="Password" type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} error={errors.password} />
        <TextField label="Authenticator or recovery code" required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} error={errors.code} />
        <Button type="submit" variant="danger" loading={disable.isPending}>
          Turn off
        </Button>
      </form>
    </details>
  );
}

function PasswordSection() {
  const [form, setForm] = useState({ current_password: "", new_password: "" });
  const change = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/password/change/", { body: form })),
    onSuccess: () => setForm({ current_password: "", new_password: "" }),
  });
  const errors = change.error instanceof ApiError ? change.error.fieldErrors() : {};
  return (
    <Section title="Password">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          change.mutate();
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        {change.isSuccess && <p role="status">Password changed. Your other sessions were signed out.</p>}
        {change.error && !Object.keys(errors).length && <ErrorAlert error={change.error} />}
        <TextField label="Current password" type="password" autoComplete="current-password" required value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} error={errors.current_password} />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          value={form.new_password}
          onChange={(e) => setForm({ ...form, new_password: e.target.value })}
          error={errors.new_password}
          hint="At least 10 characters. Avoid common words."
        />
        <Button type="submit" variant="secondary" loading={change.isPending} className="self-start">
          Change password
        </Button>
      </form>
    </Section>
  );
}
