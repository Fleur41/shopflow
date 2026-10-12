"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { TextField } from "@/components/ui/Field";
import { Card, ErrorAlert, Loading } from "@/components/ui/Feedback";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { can, useMe } from "@/lib/auth";
import { useCurrentStore } from "@/lib/current-store";
import { CASH_KEY } from "@/lib/query-keys";

import { CloseTillForm, TillReport } from "../till";

export default function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const currency = me?.organization?.base_currency ?? "KES";
  const [closing, setClosing] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const session = useQuery({
    queryKey: [...CASH_KEY, store?.id, "session", sessionId],
    enabled: Boolean(store),
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/cash-sessions/{session_id}/", { params: { path: { store_id: store?.id ?? "", session_id: sessionId } } })),
  });
  const data = session.data;

  return (
    <>
      <Link href="/cash" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 underline-offset-2 hover:underline">
        <ArrowLeft aria-hidden="true" className="size-4" />
        All till sessions
      </Link>
      {session.isPending && store && <Loading label="Loading the session…" />}
      {session.error && <ErrorAlert error={session.error} title="Couldn't load this session" />}
      {data && store && (
        <>
          <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
            <h1 className="text-2xl font-semibold tracking-tight">
              {data.session.till.name}: {data.session.status === "OPEN" ? "X report" : "Z report"}
            </h1>
            <div className="flex gap-2">
              {data.session.status === "OPEN" && can(me, "cash.close_session") && <Button onClick={() => setClosing(true)}>Close this till</Button>}
              {data.session.status === "CLOSED" && can(me, "cash.correct") && (
                <Button variant="secondary" onClick={() => setCorrecting(true)}>
                  Record a correction
                </Button>
              )}
            </div>
          </div>
          <Card>
            <TillReport data={data} currency={currency} timeZone={me?.organization?.timezone} />
          </Card>
          <Dialog open={closing} onClose={() => setClosing(false)} title="Close the till">
            <CloseTillForm storeId={store.id} sessionId={sessionId} currency={currency} onClosed={() => setClosing(false)} />
          </Dialog>
          <Dialog open={correcting} onClose={() => setCorrecting(false)} title="Correction" description="For cash found or found missing after the till was closed. The session itself stays as counted.">
            <CorrectionForm storeId={store.id} sessionId={sessionId} currency={currency} onDone={() => setCorrecting(false)} />
          </Dialog>
        </>
      )}
    </>
  );
}

function CorrectionForm({ storeId, sessionId, currency, onDone }: { storeId: string; sessionId: string; currency: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [ids] = useState(() => ({ key: newIdempotencyKey(), txn: crypto.randomUUID() }));
  const [direction, setDirection] = useState<"found" | "missing">("found");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/cash-sessions/{session_id}/corrections/", {
          params: { path: { store_id: storeId, session_id: sessionId }, header: { "Idempotency-Key": ids.key } },
          body: { client_txn_id: ids.txn, amount: direction === "missing" ? `-${amount}` : amount, reason },
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
      <fieldset className="flex gap-4">
        <legend className="mb-2 text-sm font-medium text-slate-800">Cash was</legend>
        {(["found", "missing"] as const).map((value) => (
          <label key={value} className="flex min-h-11 items-center gap-2 text-sm font-medium">
            <input type="radio" name="direction" className="size-5 accent-emerald-700" checked={direction === value} onChange={() => setDirection(value)} />
            {value === "found" ? "Found (more than counted)" : "Missing (less than counted)"}
          </label>
        ))}
      </fieldset>
      <TextField label={`Amount (${currency})`} required inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.trim())} error={errors.amount} />
      <TextField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} maxLength={300} />
      {save.error && !errors.amount && !errors.reason ? <ErrorAlert error={save.error} title="Couldn't record it" /> : null}
      <Button type="submit" loading={save.isPending}>
        Record correction
      </Button>
    </form>
  );
}
