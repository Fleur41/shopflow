"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { ApiError } from "@/lib/api/errors";
import { landingPath, useLogin } from "@/lib/auth";
import { safeNextPath } from "@/lib/navigation";

export function LoginForm() {
  const router = useRouter();
  const next = safeNextPath(useSearchParams().get("next"));
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const fieldErrors = login.error instanceof ApiError ? login.error.fieldErrors() : {};

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const me = await login.mutateAsync({ email, password }).catch(() => null);
    if (me) router.replace(landingPath(me, next));
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Sign in</h1>
      {login.error && !Object.keys(fieldErrors).length && <ErrorAlert error={login.error} title="Couldn't sign you in" />}
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
      <p className="text-center text-sm text-slate-700">
        New to ShopFlow?{" "}
        <Link href="/signup" className="font-semibold text-emerald-800 underline">
          Register your business
        </Link>
      </p>
    </form>
  );
}
