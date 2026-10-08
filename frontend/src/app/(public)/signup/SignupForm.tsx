"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { SelectField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { ApiError } from "@/lib/api/errors";
import { type SignupInput, useSignup } from "@/lib/auth";

const CURRENCIES = ["KES", "UGX", "TZS", "RWF", "ETB", "NGN", "GHS", "ZAR", "USD"];
const TIMEZONES = [
  "Africa/Nairobi",
  "Africa/Kampala",
  "Africa/Dar_es_Salaam",
  "Africa/Kigali",
  "Africa/Addis_Ababa",
  "Africa/Lagos",
  "Africa/Accra",
  "Africa/Johannesburg",
  "UTC",
];

export function SignupForm() {
  const router = useRouter();
  const signup = useSignup();
  const [form, setForm] = useState<SignupInput>({
    full_name: "",
    email: "",
    password: "",
    organization_name: "",
    store_name: "",
    currency: "KES",
    timezone: "Africa/Nairobi",
  });
  const errors = signup.error instanceof ApiError ? signup.error.fieldErrors() : {};
  const set = (field: keyof SignupInput) => (e: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: e.target.value }));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const ok = await signup.mutateAsync(form).then(() => true, () => false);
    if (ok) router.replace("/");
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Register your business</h1>
      {signup.error && !Object.keys(errors).length && <ErrorAlert error={signup.error} title="Couldn't register" />}
      <TextField label="Your name" autoComplete="name" required value={form.full_name} onChange={set("full_name")} error={errors.full_name} />
      <TextField label="Email" type="email" autoComplete="email" required value={form.email} onChange={set("email")} error={errors.email} />
      <TextField
        label="Password"
        type="password"
        autoComplete="new-password"
        required
        value={form.password}
        onChange={set("password")}
        error={errors.password}
        hint="At least 10 characters. Avoid common words."
      />
      <TextField label="Business name" required value={form.organization_name} onChange={set("organization_name")} error={errors.organization_name} />
      <TextField label="First shop name" value={form.store_name} onChange={set("store_name")} error={errors.store_name} hint="Optional. Defaults to “Main store”." />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Currency" value={form.currency} onChange={set("currency")} error={errors.currency}>
          {CURRENCIES.map((code) => (
            <option key={code}>{code}</option>
          ))}
        </SelectField>
        <SelectField label="Time zone" value={form.timezone} onChange={set("timezone")} error={errors.timezone}>
          {TIMEZONES.map((zone) => (
            <option key={zone}>{zone}</option>
          ))}
        </SelectField>
      </div>
      <Button type="submit" loading={signup.isPending}>
        Create my business
      </Button>
      <p className="text-center text-sm text-slate-700">
        Already registered?{" "}
        <Link href="/login" className="font-semibold text-emerald-800 underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
