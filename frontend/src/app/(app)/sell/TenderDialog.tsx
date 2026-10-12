"use client";

import { Banknote, CreditCard, HandCoins, Smartphone, Trash2, Wallet } from "lucide-react";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { AmountField, TextField } from "@/components/ui/Field";
import { ErrorAlert } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import type { PaymentMethod } from "@/lib/api/types";
import { type Tender, type TenderKind, cashShortcuts, fromScaled, summariseTenders, toScaled } from "@/lib/cart";

import type { TillCustomer } from "./till-state";

const ICONS = { CASH: Banknote, MOBILE_MONEY: Smartphone, CARD: CreditCard, BANK_TRANSFER: Wallet, OTHER: Wallet } as const;

/**
 * Taking payment: one or more tenders (cash with change, M-Pesa with its
 * code, card...) plus, for a chosen customer, an amount on credit. "Cash"
 * then Enter is an exact-cash sale.
 */
export function TenderForm({
  total,
  currency,
  minorUnits,
  methods,
  customer,
  canCredit,
  submitting,
  error,
  onSubmit,
}: {
  total: string;
  currency: string;
  minorUnits: number;
  methods: PaymentMethod[];
  customer: TillCustomer | null;
  canCredit: boolean;
  submitting: boolean;
  error: unknown;
  onSubmit: (tenders: Tender[], credit: string) => void;
}) {
  const [tenders, setTenders] = useState<Tender[]>([]);
  const [credit, setCredit] = useState("");
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const summary = summariseTenders(total, tenders, credit, minorUnits);
  const formId = useId();

  function add(method: PaymentMethod) {
    const existing = tenders.findIndex((tender) => tender.methodId === method.id);
    if (existing >= 0) {
      setFocusIndex(existing);
      return;
    }
    const amount = summary.remaining !== fromScaled(0n, minorUnits, { trim: false }) ? summary.remaining : "";
    setTenders([
      ...tenders,
      {
        methodId: method.id,
        name: method.name,
        kind: method.kind as TenderKind,
        requiresReference: method.requires_reference ?? false,
        amount,
        tendered: "",
        reference: "",
      },
    ]);
    setFocusIndex(tenders.length);
  }

  function change(index: number, patch: Partial<Tender>) {
    setTenders(tenders.map((tender, i) => (i === index ? { ...tender, ...patch } : tender)));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (summary.complete && !submitting) onSubmit(tenders, credit);
  }

  const creditAvailable = customer?.availableCredit ?? null;
  const showCredit = Boolean(customer && canCredit);

  return (
    <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-5">
      <div className="rounded-xl bg-ledger-900 px-5 py-4 text-white">
        <p className="text-sm text-emerald-100/80">Amount due</p>
        <Money amount={total} currency={currency} size="xl" tone="inverse" />
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-medium text-slate-800">How is the customer paying?</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {methods.map((method) => {
            const Icon = ICONS[method.kind as keyof typeof ICONS] ?? Wallet;
            const used = tenders.some((tender) => tender.methodId === method.id);
            return (
              <button
                key={method.id}
                type="button"
                onClick={() => add(method)}
                aria-pressed={used}
                className={`flex min-h-14 items-center justify-center gap-2 rounded-xl px-3 font-semibold ring-1 transition ${used ? "bg-emerald-50 text-emerald-900 ring-emerald-600" : "bg-white text-slate-900 ring-slate-300 hover:ring-slate-400"}`}
              >
                <Icon aria-hidden="true" className="size-5" />
                {method.name}
              </button>
            );
          })}
          {showCredit && (
            <button
              type="button"
              onClick={() => setCredit(credit || summary.remaining)}
              aria-pressed={Boolean(credit)}
              className={`flex min-h-14 items-center justify-center gap-2 rounded-xl px-3 font-semibold ring-1 transition ${credit ? "bg-amber-50 text-amber-950 ring-amber-500" : "bg-white text-slate-900 ring-slate-300 hover:ring-slate-400"}`}
            >
              <HandCoins aria-hidden="true" className="size-5" />
              On credit
            </button>
          )}
        </div>
      </fieldset>

      {tenders.map((tender, index) => (
        <TenderRow
          key={tender.methodId}
          tender={tender}
          currency={currency}
          minorUnits={minorUnits}
          problem={summary.problems[index]}
          focus={focusIndex === index}
          onChange={(patch) => change(index, patch)}
          onRemove={() => setTenders(tenders.filter((_, i) => i !== index))}
        />
      ))}

      {credit && customer && (
        <div className="rounded-xl bg-amber-50/60 p-4 ring-1 ring-amber-500/30">
          <div className="flex items-end gap-3">
            <div className="min-w-0 flex-1">
              <AmountField label={`On ${customer.name}'s account`} currency={currency} value={credit} onValueChange={setCredit} />
            </div>
            <Button variant="ghost" aria-label="Remove credit" onClick={() => setCredit("")}>
              <Trash2 aria-hidden="true" className="size-4" />
            </Button>
          </div>
          {creditAvailable !== null && (
            <p className="mt-2 text-sm text-amber-950">
              Available credit: <Money amount={creditAvailable} currency={currency} size="sm" />
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
        <p aria-live="polite" className="text-sm">
          {toScaled(summary.remaining, minorUnits) ? (
            <span className="text-red-800">
              Still to pay <Money amount={summary.remaining} currency={currency} size="lg" />
            </span>
          ) : toScaled(summary.change, minorUnits) ? (
            <span className="font-semibold text-emerald-900">
              Change <Money amount={summary.change} currency={currency} size="xl" />
            </span>
          ) : tenders.length || credit ? (
            <span className="font-medium text-emerald-900">Fully paid</span>
          ) : (
            <span className="text-slate-600">Choose how they’re paying.</span>
          )}
        </p>
        <Button type="submit" className="min-h-12 px-6 text-base" disabled={!summary.complete} loading={submitting}>
          Complete sale
        </Button>
      </div>
      {error ? <ErrorAlert error={error} title="The sale wasn't completed" /> : null}
    </form>
  );
}

function TenderRow({
  tender,
  currency,
  minorUnits,
  problem,
  focus,
  onChange,
  onRemove,
}: {
  tender: Tender;
  currency: string;
  minorUnits: number;
  problem: string | undefined;
  focus: boolean;
  onChange: (patch: Partial<Tender>) => void;
  onRemove: () => void;
}) {
  const primary = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focus) primary.current?.querySelector("input")?.focus();
  }, [focus]);
  const isCash = tender.kind === "CASH";
  return (
    <div className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
      <div className="mb-3 flex items-center justify-between">
        <p className="font-semibold">{tender.name}</p>
        <Button variant="ghost" aria-label={`Remove ${tender.name}`} onClick={onRemove}>
          <Trash2 aria-hidden="true" className="size-4" />
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <AmountField label="Amount" currency={currency} value={tender.amount} onValueChange={(amount) => onChange({ amount })} />
        {isCash ? (
          <div ref={primary}>
            <AmountField
              label="Cash given"
              currency={currency}
              value={tender.tendered}
              onValueChange={(tendered) => onChange({ tendered })}
              hint="Leave empty if exact."
            />
          </div>
        ) : tender.requiresReference || tender.kind === "MOBILE_MONEY" ? (
          <div ref={primary}>
            <TextField
              label={tender.kind === "MOBILE_MONEY" ? `${tender.name} code` : "Reference"}
              required={tender.requiresReference}
              value={tender.reference}
              onChange={(e) => onChange({ reference: e.target.value.toUpperCase() })}
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              maxLength={30}
              placeholder={tender.kind === "MOBILE_MONEY" ? "e.g. SK7ABC12DE" : undefined}
              className="tabular font-mono uppercase"
            />
          </div>
        ) : null}
      </div>
      {isCash && (
        <div className="mt-2 flex flex-wrap gap-2" aria-label="Quick cash amounts" role="group">
          {cashShortcuts(tender.amount, minorUnits).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onChange({ tendered: value })}
              className="tabular min-h-11 rounded-lg bg-white px-3 text-sm font-semibold ring-1 ring-slate-300 hover:ring-slate-400"
            >
              <Money amount={value} currency={currency} size="sm" />
            </button>
          ))}
        </div>
      )}
      {problem && <p className="mt-2 text-sm font-medium text-red-700">{problem}</p>}
    </div>
  );
}
