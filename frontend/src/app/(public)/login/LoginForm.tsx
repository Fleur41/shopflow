"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { ApiError } from "@/lib/api/errors";
import type { Me } from "@/lib/api/types";
import { landingPath, mfaChallengeFrom, useLogin, useVerifyMfa } from "@/lib/auth";
import { safeNextPath } from "@/lib/navigation";

export function LoginForm() {
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const done = (me: Me) => router.replace(landingPath(me, next));

  return mfaToken ? (
    <CodeStep mfaToken={mfaToken} onDone={done} onRestart={() => setMfaToken(null)} />
  ) : (
    <PasswordStep onDone={done} onMfaRequired={setMfaToken} />
  );
}

function PasswordStep({ onDone, onMfaRequired }: { onDone: (me: Me) => void; onMfaRequired: (token: string) => void }) {
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const fieldErrors = login.error instanceof ApiError ? login.error.fieldErrors() : {};

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      onDone(await login.mutateAsync({ email, password }));
    } catch (error) {
      const challenge = mfaChallengeFrom(error);
      if (challenge) onMfaRequired(challenge);
    }
  }

  const showError = login.error && !mfaChallengeFrom(login.error) && !Object.keys(fieldErrors).length;
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Sign in</h1>
      {showError && <ErrorAlert error={login.error} title="Couldn't sign you in" />}
      <TextField
        label="Email"
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        error={fieldErrors.email}
      />
      <TextField
        label="Password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={fieldErrors.password}
      />
      <Button type="submit" loading={login.isPending}>
        Sign in
      </Button>
      <p className="text-center text-sm">
        <Link href="/forgot-password" className="font-semibold text-emerald-800 underline">
          Forgot your password?
        </Link>
      </p>
      <p className="text-center text-sm text-slate-700">
        New to ShopFlow?{" "}
        <Link href="/signup" className="font-semibold text-emerald-800 underline">
          Register your business
        </Link>
      </p>
    </form>
  );
}

function CodeStep({ mfaToken, onDone, onRestart }: { mfaToken: string; onDone: (me: Me) => void; onRestart: () => void }) {
  const verify = useVerifyMfa();
  const [code, setCode] = useState("");
  const expired = verify.error instanceof ApiError && verify.error.code === "TOKEN_INVALID";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const me = await verify.mutateAsync({ mfa_token: mfaToken, code }).catch(() => null);
    if (me) onDone(me);
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Two-step verification</h1>
      <p className="text-slate-700">Enter the 6-digit code from your authenticator app.</p>
      {verify.error && <ErrorAlert error={verify.error} title="Code not accepted" />}
      <TextField
        label="Verification code"
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        autoFocus
        value={code}
        onChange={(e) => setCode(e.target.value)}
        hint="Lost your phone? Enter one of your recovery codes instead."
      />
      {expired ? (
        <Button onClick={onRestart}>Start again</Button>
      ) : (
        <Button type="submit" loading={verify.isPending}>
          Verify
        </Button>
      )}
    </form>
  );
}
