"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { AmountField, SelectField, TextField } from "@/components/ui/Field";
import { Badge, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { SessionReport } from "@/lib/api/types";
import { fromScaled, toScaled } from "@/lib/cart";
import { minorUnits } from "@/lib/money";
import { CASH_KEY } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/sales";

/** The caller's open till session in a store (blind: no expected cash). */
export function useCurrentSession(storeId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: [...CASH_KEY, storeId, "current"],
    enabled: Boolean(storeId) && enabled,
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/cash-sessions/current/", { params: { path: { store_id: storeId ?? "" } } })),
    select: (data) => data.session,
  });
}

export function OpenTillForm({ storeId, currency, onDone }: { storeId: string; currency: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [ids] = useState(() => ({ key: newIdempotencyKey(), txn: crypto.randomUUID() }));
  const [tillId, setTillId] = useState("");
  const [float, setFloat] = useState("");
  const tills = useQuery({
    queryKey: [...CASH_KEY, storeId, "tills"],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/tills/", { params: { path: { store_id: storeId } } })),
    select: (all) => all.filter((till) => till.is_active),
  });
  const till = tills.data?.find((t) => t.id === tillId) ?? tills.data?.[0];
  const open = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/cash-sessions/", {
          params: { path: { store_id: storeId }, header: { "Idempotency-Key": ids.key } },
          body: { client_txn_id: ids.txn, till_id: till?.id ?? "", opening_float: float || "0" },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CASH_KEY });
      onDone();
    },
  });
  const errors = open.error instanceof ApiError ? open.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    open.mutate();
  }
  if (tills.isPending) return <Loading label="Loading tills…" />;
  if (tills.error) return <ErrorAlert error={tills.error} title="Couldn't load the tills" />;
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      {(tills.data?.length ?? 0) > 1 && (
        <SelectField label="Till" value={till?.id ?? ""} onChange={(e) => setTillId(e.target.value)}>
          {tills.data?.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </SelectField>
      )}
      <AmountField
        label="Cash in the drawer now"
        currency={currency}
        value={float}
        onValueChange={setFloat}
        error={errors.opening_float}
        hint="The float: change you start with. Count it."
        autoFocus
      />
      {open.error && !errors.opening_float ? <ErrorAlert error={open.error} title="Couldn't open the till" /> : null}
      <Button type="submit" loading={open.isPending} disabled={!till}>
        Open {till?.name ?? "till"}
      </Button>
    </form>
  );
}

const MOVEMENTS = {
  PAY_IN: { label: "Pay in", hint: "Cash added, e.g. more change from the bank." },
  PAY_OUT: { label: "Pay out", hint: "Cash taken for an expense, e.g. airtime or transport." },
  DROP: { label: "Safe drop", hint: "Cash moved from the drawer to the safe." },
} as const;

export function CashMovementForm({ storeId, sessionId, currency, onDone }: { storeId: string; sessionId: string; currency: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [ids] = useState(() => ({ key: newIdempotencyKey(), txn: crypto.randomUUID() }));
  const [kind, setKind] = useState<keyof typeof MOVEMENTS>("PAY_OUT");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/cash-sessions/{session_id}/movements/", {
          params: { path: { store_id: storeId, session_id: sessionId }, header: { "Idempotency-Key": ids.key } },
          body: { client_txn_id: ids.txn, movement_type: kind, amount, reason },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CASH_KEY });
      onDone();
    },
  });
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <SelectField label="What" value={kind} onChange={(e) => setKind(e.target.value as keyof typeof MOVEMENTS)} hint={MOVEMENTS[kind].hint}>
        {Object.entries(MOVEMENTS).map(([value, { label }]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </SelectField>
      <AmountField label="Amount" required currency={currency} value={amount} onValueChange={setAmount} error={errors.amount} />
      <TextField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} maxLength={300} />
      {save.error && !errors.amount && !errors.reason ? <ErrorAlert error={save.error} title="Couldn't record it" /> : null}
      <Button type="submit" loading={save.isPending}>
        Record {MOVEMENTS[kind].label.toLowerCase()}
      </Button>
    </form>
  );
}

// Kenyan notes and coins; other currencies count the total only.
const DENOMINATIONS: Record<string, string[]> = { KES: ["1000", "500", "200", "100", "50", "20", "10", "5", "1"] };

/**
 * The blind close-out: count the drawer before seeing what should be there.
 * Counting note by note adds up the total for you.
 */
export function CloseTillForm({
  storeId,
  sessionId,
  currency,
  onClosed,
}: {
  storeId: string;
  sessionId: string;
  currency: string;
  onClosed: (report: SessionReport) => void;
}) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const notes = DENOMINATIONS[currency] ?? [];
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [total, setTotal] = useState("");
  const [reason, setReason] = useState("");
  const digits = minorUnits(currency);
  const byNotes = notes.length > 0 && Object.values(counts).some((count) => count.trim() !== "");
  const counted = byNotes
    ? fromScaled(
        notes.reduce((sum, value) => sum + BigInt(value) * BigInt(Number.parseInt(counts[value] || "0", 10) || 0), 0n) * 10n ** BigInt(digits),
        digits,
        { trim: false },
      )
    : total;
  const close = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/cash-sessions/{session_id}/close/", {
          params: { path: { store_id: storeId, session_id: sessionId }, header: { "Idempotency-Key": key } },
          body: {
            counted_cash: counted || "0",
            denomination_count: byNotes ? Object.fromEntries(notes.map((value) => [value, Number.parseInt(counts[value] || "0", 10) || 0])) : null,
            variance_reason: reason,
          },
        }),
      ),
    onSuccess: (report) => {
      void queryClient.invalidateQueries({ queryKey: CASH_KEY });
      onClosed(report);
    },
  });
  const needsReason = close.error instanceof ApiError && close.error.code === "VARIANCE_REASON_REQUIRED";
  const errors = close.error instanceof ApiError ? close.error.fieldErrors() : {};
  function submit(event: FormEvent) {
    event.preventDefault();
    if (toScaled(counted || "0", digits) === null) return;
    close.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <p className="text-sm text-slate-700">Count everything in the drawer. You’ll see what was expected after you submit the count.</p>
      {notes.length > 0 && (
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-slate-800">Notes and coins</legend>
          <div className="grid grid-cols-3 gap-2">
            {notes.map((value) => (
              <label key={value} className="flex flex-col gap-1 text-sm">
                <span className="tabular font-medium text-slate-700">
                  {currency} {value}
                </span>
                <input
                  inputMode="numeric"
                  value={counts[value] ?? ""}
                  onChange={(e) => setCounts({ ...counts, [value]: e.target.value.replace(/\D/g, "") })}
                  aria-label={`How many ${currency} ${value}`}
                  className="tabular min-h-11 rounded-lg border border-slate-300 px-3 text-right text-base focus:border-emerald-600 focus:outline-none focus:ring-4 focus:ring-emerald-600/15"
                />
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {byNotes ? (
        <p className="flex items-baseline justify-between rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-200">
          <span className="text-sm font-medium">Counted</span>
          <Money amount={counted} currency={currency} size="lg" />
        </p>
      ) : (
        <AmountField label={notes.length ? "Or the total counted" : "Total counted"} required currency={currency} value={total} onValueChange={setTotal} error={errors.counted_cash} />
      )}
      {(needsReason || reason) && (
        <TextField
          label="Why doesn’t it add up?"
          required
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          error={errors.variance_reason ? "The count is out by more than the store allows: say why." : undefined}
          autoFocus={needsReason}
          maxLength={300}
        />
      )}
      {close.error && !needsReason ? <ErrorAlert error={close.error} title="Couldn't close the till" /> : null}
      <Button type="submit" loading={close.isPending}>
        Close till
      </Button>
    </form>
  );
}

/** X report (open) or Z report (closed). */
export function TillReport({ data, currency, timeZone }: { data: SessionReport; currency: string; timeZone: string | undefined }) {
  const { session, report, movements } = data;
  const variance = report.variance === null || report.variance === undefined ? null : report.variance;
  const out = variance !== null && Number(variance) !== 0;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
        <Badge tone={session.status === "OPEN" ? "success" : "neutral"}>{session.status === "OPEN" ? "Open" : "Closed"}</Badge>
        <span>
          {session.till.name} · opened {formatDateTime(session.opened_at, timeZone)} by {session.opened_by.name}
          {session.closed_at && session.closed_by && ` · closed ${formatDateTime(session.closed_at, timeZone)} by ${session.closed_by.name}`}
        </span>
      </div>
      {variance !== null && (
        <div className={`grid grid-cols-3 gap-3 rounded-xl p-4 ring-1 ${out ? "bg-amber-50 ring-amber-500/30" : "bg-emerald-50 ring-emerald-600/20"}`}>
          <Figure label="Expected" amount={report.expected_cash} currency={currency} />
          <Figure label="Counted" amount={report.counted_cash ?? "0"} currency={currency} />
          <Figure label={Number(variance) < 0 ? "Short" : Number(variance) > 0 ? "Over" : "Exact"} amount={variance} currency={currency} signed />
        </div>
      )}
      {session.variance_reason && <p className="text-sm text-slate-700">Reason: {session.variance_reason}</p>}
      {Number(report.corrections) !== 0 && (
        <p className="text-sm text-slate-700">
          Corrected later by <Money amount={report.corrections} currency={currency} size="sm" tone="signed" />: now out by{" "}
          <Money amount={report.variance_after_corrections ?? "0"} currency={currency} size="sm" tone="signed" />
        </p>
      )}
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Row label="Opening float" amount={report.opening_float} currency={currency} />
        <Row label={`Sales (${report.sales_count})`} amount={report.sales_total} currency={currency} />
        {report.by_method.map((method) => (
          <Row key={method.method} label={`  ${method.method} (${method.count})`} amount={method.total} currency={currency} />
        ))}
        {Number(report.on_credit) > 0 && <Row label="On credit" amount={report.on_credit} currency={currency} />}
        <Row label="Cash taken" amount={report.cash_in} currency={currency} />
        <Row label="Cash paid back" amount={report.cash_out} currency={currency} />
        <Row label="Pay-ins" amount={report.pay_ins} currency={currency} />
        <Row label="Pay-outs" amount={report.pay_outs} currency={currency} />
        <Row label="Safe drops" amount={report.drops} currency={currency} />
        {report.voids_count > 0 && <Row label={`Voids (${report.voids_count})`} amount={report.voids_total} currency={currency} />}
        {report.returns_count > 0 && <Row label={`Returns (${report.returns_count})`} amount={report.returns_total} currency={currency} />}
        {variance === null && <Row label="Should be in the drawer" amount={report.expected_cash} currency={currency} strong />}
      </dl>
      {movements.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">Cash in and out</h3>
          <ul className="flex flex-col divide-y divide-slate-100 text-sm">
            {movements.map((movement) => (
              <li key={movement.id} className="flex justify-between gap-3 py-2">
                <span className="min-w-0">
                  <span className="font-medium">{MOVEMENTS[movement.movement_type as keyof typeof MOVEMENTS]?.label ?? "Correction"}</span> · {movement.reason}
                  <span className="block text-xs text-slate-600">
                    {formatDateTime(movement.occurred_at, timeZone)} · {movement.created_by}
                  </span>
                </span>
                <Money amount={movement.amount} currency={currency} size="sm" />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Figure({ label, amount, currency, signed = false }: { label: string; amount: string; currency: string; signed?: boolean }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-700">{label}</p>
      <Money amount={signed ? amount.replace(/^-/, "") : amount} currency={currency} size="lg" />
    </div>
  );
}

function Row({ label, amount, currency, strong = false }: { label: string; amount: string; currency: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className={`whitespace-pre text-slate-700 ${strong ? "font-semibold text-slate-900" : ""}`}>{label}</dt>
      <dd>
        <Money amount={amount} currency={currency} size={strong ? "md" : "sm"} />
      </dd>
    </div>
  );
}
