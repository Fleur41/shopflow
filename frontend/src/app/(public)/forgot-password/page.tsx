"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { useMutation } from "@tanstack/react-query";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const request = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/password/reset/", { body: { email } })),
  });
  const errors = request.error instanceof ApiError ? request.error.fieldErrors() : {};

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    request.mutate();
  }

  if (request.isSuccess) {
    return (
      <div role="status" className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Check your email</h1>
        <p className="text-slate-700">
          If an account exists for {email}, we’ve sent a link to reset the password. It works for 30 minutes.
        </p>
        <Link href="/login" className="font-semibold text-emerald-800 underline">
          Back to sign in
        </Link>
      </div>
    );
  }
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Reset your password</h1>
      <p className="text-slate-700">Enter your email and we’ll send you a link to choose a new password.</p>
      {request.error && !Object.keys(errors).length && <ErrorAlert error={request.error} />}
      <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} />
      <Button type="submit" loading={request.isPending}>
        Send reset link
      </Button>
      <Link href="/login" className="text-center text-sm font-semibold text-emerald-800 underline">
        Back to sign in
      </Link>
    </form>
  );
}
