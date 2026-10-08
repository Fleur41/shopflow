"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";

export function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const reset = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/auth/password/reset/confirm/", { body: { token, new_password: password } })),
  });
  const errors = reset.error instanceof ApiError ? reset.error.fieldErrors() : {};

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setMismatch(password !== confirmation);
    if (password === confirmation) reset.mutate();
  }

  if (reset.isSuccess) {
    return (
      <div role="status" className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Password changed</h1>
        <p className="text-slate-700">For your security, you’ve been signed out everywhere. Sign in with your new password.</p>
        <Link href="/login" className="font-semibold text-emerald-800 underline">
          Sign in
        </Link>
      </div>
    );
  }
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Choose a new password</h1>
      {reset.error && !Object.keys(errors).length && <ErrorAlert error={reset.error} title="Couldn't reset your password" />}
      <TextField
        label="New password"
        type="password"
        autoComplete="new-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={errors.new_password}
        hint="At least 10 characters. Avoid common words."
      />
      <TextField
        label="Repeat new password"
        type="password"
        autoComplete="new-password"
        required
        value={confirmation}
        onChange={(e) => setConfirmation(e.target.value)}
        error={mismatch ? "The passwords don’t match." : undefined}
      />
      <Button type="submit" loading={reset.isPending}>
        Change password
      </Button>
    </form>
  );
}
