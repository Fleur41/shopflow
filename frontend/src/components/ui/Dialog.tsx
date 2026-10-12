"use client";

import { X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";

/**
 * Modal dialog on the native <dialog> element: the browser provides focus
 * trapping, Escape to close and inertness of the page behind it.
 *
 * Its height follows the *dynamic* viewport (dvh): on phones, 100vh is taller
 * than what's visible, which pushed the title and the submit button off screen.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(36rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl bg-white p-0 shadow-raised ring-1 ring-slate-900/5"
    >
      <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-100 bg-white/95 px-6 py-4 backdrop-blur">
        <div>
          <h2 id={titleId} className="text-lg font-semibold tracking-tight">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-slate-600">{description}</p>}
        </div>
        <button type="button" onClick={onClose} className="-mr-2 flex size-11 shrink-0 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-900" aria-label="Close">
          <X aria-hidden="true" className="size-5" />
        </button>
      </div>
      <div className="px-6 py-5">{open && children}</div>
    </dialog>
  );
}
