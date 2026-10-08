"use client";

import { type ReactNode, useEffect, useId, useRef } from "react";

/**
 * Modal dialog on the native <dialog> element: the browser provides focus
 * trapping, Escape to close and inertness of the page behind it.
 */
export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
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
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg bg-white p-0 shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        <button type="button" onClick={onClose} className="rounded-md p-2 text-slate-700 hover:bg-slate-100" aria-label="Close">
          ✕
        </button>
      </div>
      <div className="px-5 py-4">{open && children}</div>
    </dialog>
  );
}
