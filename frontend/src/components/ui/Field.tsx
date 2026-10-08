import { type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useId } from "react";

type Common = { label: string; error?: string; hint?: ReactNode };

function describedBy(id: string, error?: string, hint?: ReactNode) {
  return [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
}

function Messages({ id, error, hint }: { id: string; error?: string; hint?: ReactNode }) {
  return (
    <>
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-slate-600">
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
  "min-h-11 w-full rounded-md border border-slate-400 bg-white px-3 py-2 text-base aria-[invalid=true]:border-red-700";

export function TextField({ label, error, hint, ...props }: Common & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {props.required && <span className="text-red-700"> *</span>}
      </label>
      <input id={id} {...props} aria-invalid={Boolean(error)} aria-describedby={describedBy(id, error, hint)} className={control} />
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
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <select id={id} {...props} aria-invalid={Boolean(error)} aria-describedby={describedBy(id, error, hint)} className={control}>
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
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
      </div>
      <Messages id={id} error={error} hint={hint} />
    </div>
  );
}
