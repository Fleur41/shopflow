"use client";

import { ArrowLeftRight, Lock, LockOpen } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import type { SessionReport } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";

import { CashMovementForm, CloseTillForm, OpenTillForm, TillReport, useCurrentSession } from "../cash/till";

/** Whether the cashier's till is open, with open / cash in-out / close at hand. */
export function TillBar({ storeId, currency }: { storeId: string; currency: string }) {
  const { data: me } = useMe();
  const allowed = can(me, "cash.open_session");
  const current = useCurrentSession(storeId, allowed);
  const [dialog, setDialog] = useState<"open" | "move" | "close" | null>(null);
  const [closed, setClosed] = useState<SessionReport | null>(null);
  const time = (iso: string) => new Intl.DateTimeFormat("en-KE", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: me?.organization?.timezone }).format(new Date(iso));

  if (!allowed || current.isPending) return null;
  const session = current.data ?? null;

  return (
    <>
      {session ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white px-4 py-2 shadow-card ring-1 ring-slate-200">
          <p className="flex items-center gap-2 text-sm">
            <LockOpen aria-hidden="true" className="size-4 text-emerald-700" />
            <span>
              <strong className="font-semibold">{session.till.name}</strong> open since {time(session.opened_at)}
            </span>
          </p>
          <div className="flex gap-2">
            {can(me, "cash.pay_in_out") && (
              <Button variant="ghost" onClick={() => setDialog("move")}>
                <ArrowLeftRight aria-hidden="true" className="size-4" /> Cash in/out
              </Button>
            )}
            {can(me, "cash.close_session") && (
              <Button variant="secondary" onClick={() => setDialog("close")}>
                <Lock aria-hidden="true" className="size-4" /> Close till
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2">
          <p className="flex items-center gap-2 text-sm text-amber-950">
            <Lock aria-hidden="true" className="size-4 text-amber-700" />
            The till is closed. Open it to take cash.
          </p>
          <Button onClick={() => setDialog("open")}>Open till</Button>
        </div>
      )}
      <Dialog open={dialog === "open"} onClose={() => setDialog(null)} title="Open the till">
        <OpenTillForm storeId={storeId} currency={currency} onDone={() => setDialog(null)} />
      </Dialog>
      <Dialog open={dialog === "move"} onClose={() => setDialog(null)} title="Cash in or out">
        {session && <CashMovementForm storeId={storeId} sessionId={session.id} currency={currency} onDone={() => setDialog(null)} />}
      </Dialog>
      <Dialog
        open={dialog === "close" || closed !== null}
        onClose={() => {
          setDialog(null);
          setClosed(null);
        }}
        title={closed ? "Till closed" : "Close the till"}
      >
        {closed ? (
          <TillReport data={closed} currency={currency} timeZone={me?.organization?.timezone} />
        ) : (
          session && (
            <CloseTillForm
              storeId={storeId}
              sessionId={session.id}
              currency={currency}
              onClosed={(report) => {
                setDialog(null);
                setClosed(report);
              }}
            />
          )
        )}
      </Dialog>
    </>
  );
}
