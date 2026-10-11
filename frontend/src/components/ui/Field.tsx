"use client";

import { type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useId } from "react";

import { minorUnits, normaliseTypedAmount } from "@/lib/money";

type Common = { label: string; error?: string; hint?: ReactNode };

function describedBy(id: string, error?: string, hint?: ReactNode) {
  return [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
}

function Messages({ id, error, hint }: { id: string; error?: string; hint?: ReactNode }) {
  return (
    <>
      {hint && (
        <p id={`${id}-hint`} className="text-[0.8125rem] leading-5 text-slate-600">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-sm font-medium text-red-700">
          {error}
        </p>
      )}
    </>
  );
}

const control =
  "min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 shadow-sm transition-[border-color,box-shadow] placeholder:text-slate-500 hover:border-slate-400 focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15 focus:outline-none disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-600 aria-[invalid=true]:border-red-700 aria-[invalid=true]:focus:ring-red-700/15";

export function TextField({ label, error, hint, ...props }: Common & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-800">
        {label}
        {props.required && <span className="text-red-700"> *</span>}
      </label>
      <input id={id} {...props} aria-invalid={Boolean(error)} aria-describedby={describedBy(id, error, hint)} className={`${control} ${props.className ?? ""}`} />
      <Messages id={id} error={error} hint={hint} />
    </div>
  );
}

/**
 * A money input: the currency sits inside the field, figures are tabular, and
 * "150" becomes "150.00" when you leave it (at the currency's precision).
 */
export function AmountField({
  label,
  error,
  hint,
  currency,
  value,
  onValueChange,
  ...props
}: Common &
  Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
    currency: string | undefined;
    value: string;
    onValueChange: (value: string) => void;
  }) {
  const id = useId();
  const code = currency ?? "";
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-800">
        {label}
        {props.required && <span className="text-red-700"> *</span>}
      </label>
      <div className="relative">
        {code && (
          <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-xs font-semibold tracking-wider text-slate-600">
            {code}
          </span>
        )}
        <input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          {...props}
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          onBlur={(e) => {
            if (code) onValueChange(normaliseTypedAmount(value, code));
            props.onBlur?.(e);
          }}
          placeholder={code ? (minorUnits(code) ? `0.${"0".repeat(minorUnits(code))}` : "0") : props.placeholder}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy(id, error, hint)}
          className={`${control} tabular text-right font-medium ${code ? "pl-14" : ""}`}
        />
      </div>
      <Messages id={id} error={error} hint={hint} />
    </div>
  );
}

export function SelectField({
  label,
  error,
  hint,
  children,
  ...props
}: Common & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-800">
        {label}
        {props.required && <span className="text-red-700"> *</span>}
      </label>
      <select id={id} {...props} aria-invalid={Boolean(error)} aria-describedby={describedBy(id, error, hint)} className={`${control} select-chevron ${props.className ?? ""}`}>
        {children}
      </select>
      <Messages id={id} error={error} hint={hint} />
    </div>
  );
}

export function CheckboxField({ label, error, hint, ...props }: Common & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex min-h-11 items-center gap-3">
        <input id={id} type="checkbox" {...props} aria-describedby={describedBy(id, error, hint)} className="size-5 accent-emerald-700" />
        <label htmlFor={id} className="text-sm font-medium text-slate-800">
          {label}
        </label>
      </div>
      <Messages id={id} error={error} hint={hint} />
    </div>
  );
}
