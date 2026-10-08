"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { ErrorAlert } from "@/components/ui/Feedback";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** Confirmation needs a click: link scanners in mail systems must not use up the token. */
export function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const verify = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/email/verify/", { body: { token } })),
  });

  if (verify.isSuccess) {
    return (
      <div role="status" className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Email confirmed</h1>
        <p className="text-slate-700">Thanks. Your email address is confirmed.</p>
        <Link href="/" className="font-semibold text-emerald-800 underline">
          Continue to ShopFlow
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Confirm your email</h1>
      {verify.error && <ErrorAlert error={verify.error} title="Couldn't confirm" />}
      <Button onClick={() => verify.mutate()} loading={verify.isPending}>
        Confirm my email address
      </Button>
    </div>
  );
}
