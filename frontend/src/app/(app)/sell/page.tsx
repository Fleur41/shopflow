"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, CircleCheck, Minus, Plus, Printer, ScanBarcode, Search, ShoppingBasket, Trash2, UserRound, X } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { CameraScanner, cameraScanningSupported } from "@/components/CameraScanner";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, EmptyState, ErrorAlert, Loading, Notice } from "@/components/ui/Feedback";
import { Money } from "@/components/ui/Money";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import type { Lookup, Product, Sale } from "@/lib/api/types";
import { can, useMe } from "@/lib/auth";
import { type CartLine, type Tender, addToCart, priceLines, quantityProblem, removeLine, repriceLines, setQuantity, shortOfStock, stepQuantity } from "@/lib/cart";
import { useCurrentStore } from "@/lib/current-store";
import { formatAmount, minorUnits } from "@/lib/money";
import { CASH_KEY, PAYMENT_METHODS_KEY } from "@/lib/query-keys";
import { useScannerWedge } from "@/lib/scanner";

import { CustomerPicker } from "./CustomerPicker";
import { TenderForm } from "./TenderDialog";
import { TillBar } from "./TillBar";
import { useTillState } from "./till-state";

type ScanMessage = { tone: "error" | "info"; text: string } | null;

const noSubscription = () => () => undefined;

export default function SellPage() {
  const { data: me } = useMe();
  const [store] = useCurrentStore(me);
  const currency = me?.organization?.base_currency ?? "KES";
  const digits = minorUnits(currency);
  const taxMode = me?.organization?.tax_mode ?? "INCLUSIVE";
  const storageKey = me?.organization && store ? `shopflow:till:${me.organization.id}:${store.id}` : null;
  const { state, update, clear } = useTillState(storageKey);
  const queryClient = useQueryClient();

  const [code, setCode] = useState("");
  const [message, setMessage] = useState<ScanMessage>(null);
  const [matches, setMatches] = useState<Product[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [picking, setPicking] = useState(false);
  const [camera, setCamera] = useState(false);
  const [completed, setCompleted] = useState<Sale | null>(null);
  const cameraAvailable = useSyncExternalStore(noSubscription, cameraScanningSupported, () => false);
  const scanInput = useRef<HTMLInputElement>(null);
  const cache = useRef(new Map<string, Lookup>());

  useEffect(() => {
    cache.current.clear(); // prices and stock are per store
  }, [store?.id]);

  const methods = useQuery({
    queryKey: [...PAYMENT_METHODS_KEY, "till"],
    queryFn: () => unwrap(api.GET("/api/v1/payment-methods/", { params: { query: { is_active: true, page_size: 50 } } })),
    select: (page) => [...page.results].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)),
  });

  const priced = priceLines(state.lines, digits, taxMode);
  const itemCount = state.lines.length;

  const focusScan = useCallback(() => scanInput.current?.focus(), []);

  const addCode = useCallback(
    async (raw: string) => {
      const scanned = raw.trim();
      if (!scanned || !store) return;
      setMessage(null);
      setMatches(null);
      if (completed) setCompleted(null);
      let found = cache.current.get(scanned);
      if (!found) {
        try {
          found = await unwrap(api.GET("/api/v1/stores/{store_id}/products/lookup/", { params: { path: { store_id: store.id }, query: { code: scanned } } }));
          cache.current.set(scanned, found);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            if (/[a-z]/i.test(scanned) && scanned.length >= 2) {
              const results = await unwrap(api.GET("/api/v1/products/", { params: { query: { search: scanned, is_active: true, page_size: 8 } } })).catch(() => null);
              if (results && results.results.length > 0) {
                setMatches(results.results);
                return;
              }
            }
            setMessage({ tone: "error", text: `No product has the code “${scanned}”.` });
          } else {
            setMessage({ tone: "error", text: error instanceof Error ? error.message : "Couldn't look that up." });
          }
          return;
        }
      }
      if (!found.is_active) {
        setMessage({ tone: "error", text: `${found.name} is no longer sold.` });
        return;
      }
      update((current) => ({ ...current, lines: addToCart(current.lines, found, scanned) }));
      setMessage({ tone: "info", text: `Added ${found.name}` });
    },
    [completed, store, update],
  );

  useScannerWedge((scanned) => void addCode(scanned), !paying && !picking && !camera);

  // F2 scan, F4 customer, F8 pay: the till works without a mouse.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (paying || picking || camera) return;
      if (event.key === "F2") {
        event.preventDefault();
        focusScan();
      } else if (event.key === "F4") {
        event.preventDefault();
        setPicking(true);
      } else if (event.key === "F8" && priced) {
        event.preventDefault();
        setPaying(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [camera, focusScan, paying, picking, priced]);

  function submitCode(event: FormEvent) {
    event.preventDefault();
    const value = code;
    setCode("");
    void addCode(value);
  }

  const sell = useMutation({
    mutationFn: ({ tenders, credit }: { tenders: Tender[]; credit: string }) =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/sales/", {
          params: { path: { store_id: store?.id ?? "" }, header: { "Idempotency-Key": newIdempotencyKey() } },
          body: {
            client_txn_id: state.txnId,
            customer_id: state.customer?.id ?? null,
            items: state.lines.map((line) => ({
              product_id: line.productId,
              quantity: line.quantity,
              unit_price: line.unitPrice,
              discount_amount: "0",
              price_override: false,
              override_reason: "",
              scanned_code: line.scannedCode,
            })),
            tenders: tenders.map((tender) => ({
              payment_method_id: tender.methodId,
              amount: tender.amount,
              tendered: tender.kind === "CASH" && tender.tendered ? tender.tendered : null,
              reference: tender.reference.trim(),
            })),
            order_discount: "0",
            credit_amount: credit || "0",
            notes: "",
          },
        }),
      ),
    onSuccess: (sale) => {
      void queryClient.invalidateQueries({ queryKey: CASH_KEY });
      setPaying(false);
      setCompleted(sale);
      setNotice(null);
      cache.current.clear(); // stock changed
      clear();
      sell.reset();
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) return;
      if (error.code === "PRICE_CHANGED") {
        const prices: Record<string, string> = {};
        for (const problem of error.problem.errors ?? []) {
          const meta = problem.meta as { product_id?: string; current?: string } | undefined;
          if (meta?.product_id && meta.current) prices[meta.product_id] = meta.current;
        }
        update((current) => ({ ...current, lines: repriceLines(current.lines, prices) }));
        cache.current.clear();
        setPaying(false);
        setNotice(`${error.problem.detail} The cart now shows the new prices.`);
        sell.reset();
      } else if (error.code === "INSUFFICIENT_STOCK" || error.code === "PRODUCT_INACTIVE") {
        setPaying(false);
        setNotice(error.problem.detail);
        cache.current.clear();
        sell.reset();
      }
    },
  });

  if (!store) {
    return <EmptyState title="No store to sell from">You aren’t assigned to a store yet. Ask the owner to give you access.</EmptyState>;
  }

  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-emerald-800">
            {store.code} · {store.name}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">Sell</h1>
        </div>
        <p className="hidden text-xs text-slate-600 lg:block">
          <kbd className="kbd">F2</kbd> scan · <kbd className="kbd">F4</kbd> customer · <kbd className="kbd">F8</kbd> pay
        </p>
      </div>

      <TillBar storeId={store.id} currency={currency} />

      {completed && <SaleComplete sale={completed} storeId={store.id} onNext={() => { setCompleted(null); focusScan(); }} />}

      {!completed && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 pb-28 lg:grid-cols-[minmax(0,1fr)_22rem] lg:pb-0">
          <div className="flex min-w-0 flex-col gap-4">
            <form onSubmit={submitCode} className="flex gap-2" role="search" aria-label="Add a product">
              <div className="relative min-w-0 flex-1">
                <label htmlFor="scan" className="sr-only">
                  Scan a barcode, or type a code or name
                </label>
                <ScanBarcode aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-slate-500" />
                <input
                  id="scan"
                  ref={scanInput}
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="Scan, or type a code or name"
                  autoComplete="off"
                  spellCheck={false}
                  enterKeyHint="search"
                  className="min-h-12 w-full rounded-xl border border-slate-300 bg-white pl-11 pr-3 text-base shadow-sm focus:border-emerald-600 focus:outline-none focus:ring-4 focus:ring-emerald-600/15"
                />
              </div>
              <Button type="submit" variant="secondary" className="min-h-12" aria-label="Find">
                <Search aria-hidden="true" className="size-5" />
              </Button>
              {cameraAvailable && (
                <Button className="min-h-12" onClick={() => setCamera(true)} aria-label="Scan with camera">
                  <Camera aria-hidden="true" className="size-5" />
                </Button>
              )}
            </form>
            <p aria-live="polite" className={`min-h-5 text-sm ${message?.tone === "error" ? "font-medium text-red-700" : "text-emerald-800"}`}>
              {message?.text}
            </p>
            {matches && (
              <ul aria-label="Matching products" className="-mt-2 flex flex-col divide-y divide-slate-100 rounded-xl bg-white ring-1 ring-slate-200">
                {matches.map((product) => (
                  <li key={product.id}>
                    <button
                      type="button"
                      onClick={() => void addCode(product.sku ?? "")}
                      className="flex min-h-12 w-full items-center justify-between gap-3 px-4 text-left hover:bg-emerald-50"
                    >
                      <span className="min-w-0 truncate font-medium">{product.name}</span>
                      <span className="tabular shrink-0 font-mono text-xs text-slate-600">{product.sku}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {notice && (
              <Notice>
                <div className="flex items-start justify-between gap-2">
                  <p>{notice}</p>
                  <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss" className="-m-2 flex size-11 shrink-0 items-center justify-center rounded-lg hover:bg-amber-100">
                    <X aria-hidden="true" className="size-4" />
                  </button>
                </div>
              </Notice>
            )}

            {itemCount === 0 ? (
              <EmptyState icon={ShoppingBasket} title="Scan the first item">
                Use a barcode scanner{cameraAvailable ? ", the camera button" : ""} or type a barcode, SKU or product name.
              </EmptyState>
            ) : (
              <Cart
                lines={state.lines}
                currency={currency}
                lineTotals={priced?.lines.map((line) => line.line_total) ?? null}
                onChange={(lines) => update((current) => ({ ...current, lines }))}
              />
            )}
          </div>

          <aside aria-label="Sale total" className="lg:sticky lg:top-6 lg:self-start">
            <div className="flex flex-col gap-4 rounded-2xl bg-white p-5 shadow-card ring-1 ring-slate-200">
              <div className="flex items-center justify-between gap-3">
                {state.customer ? (
                  <div className="min-w-0">
                    <p className="text-xs text-slate-600">Customer</p>
                    <p className="truncate font-semibold">{state.customer.name}</p>
                  </div>
                ) : (
                  <p className="text-sm text-slate-600">Walk-in customer</p>
                )}
                <div className="flex shrink-0 gap-1">
                  {state.customer && (
                    <Button variant="ghost" aria-label="Remove customer" onClick={() => update((current) => ({ ...current, customer: null }))}>
                      <X aria-hidden="true" className="size-4" />
                    </Button>
                  )}
                  {can(me, "customers.view") && (
                    <Button variant="secondary" onClick={() => setPicking(true)}>
                      <UserRound aria-hidden="true" className="size-4" /> {state.customer ? "Change" : "Customer"}
                    </Button>
                  )}
                </div>
              </div>
              <dl className="flex flex-col gap-1.5 border-t border-slate-100 pt-4 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-600">Items</dt>
                  <dd className="tabular">{itemCount}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-600">{taxMode === "INCLUSIVE" ? "Tax included" : "Tax"}</dt>
                  <dd>
                    <Money amount={priced?.tax_total ?? "0"} currency={currency} size="sm" />
                  </dd>
                </div>
                <div className="flex items-baseline justify-between pt-2">
                  <dt className="font-semibold">Total</dt>
                  <dd>
                    <Money amount={priced?.total ?? "0"} currency={currency} size="xl" />
                  </dd>
                </div>
              </dl>
              <Button className="hidden min-h-12 text-base lg:inline-flex" disabled={!priced} onClick={() => setPaying(true)}>
                Charge <span className="tabular">{formatAmount(priced?.total ?? "0", currency)?.text}</span>
              </Button>
              {itemCount > 0 && (
                <Button variant="ghost" className="text-red-800" onClick={() => { if (window.confirm("Clear this sale?")) clear(); }}>
                  Clear sale
                </Button>
              )}
            </div>
          </aside>

          {/* Phones: the total and the pay button stay in reach of the thumb. */}
          <div className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur lg:hidden">
            <Button className="min-h-12 w-full text-base" disabled={!priced} onClick={() => setPaying(true)}>
              Charge <span className="tabular">{formatAmount(priced?.total ?? "0", currency)?.text}</span>
            </Button>
          </div>
        </div>
      )}

      <Dialog open={paying} onClose={() => { if (!sell.isPending) setPaying(false); }} title="Take payment">
        {methods.isPending && <Loading label="Loading payment methods…" />}
        {methods.error && <ErrorAlert error={methods.error} title="Couldn't load payment methods" />}
        {methods.data && priced && (
          <TenderForm
            total={priced.total}
            currency={currency}
            minorUnits={digits}
            methods={methods.data}
            customer={state.customer}
            canCredit={can(me, "sales.credit")}
            submitting={sell.isPending}
            error={sell.error}
            onSubmit={(tenders, credit) => sell.mutate({ tenders, credit })}
          />
        )}
      </Dialog>
      <Dialog open={picking} onClose={() => setPicking(false)} title="Customer for this sale">
        <CustomerPicker
          currency={currency}
          canCreate={can(me, "customers.create")}
          onPick={(customer) => {
            update((current) => ({ ...current, customer }));
            setPicking(false);
          }}
        />
      </Dialog>
      <Dialog open={camera} onClose={() => setCamera(false)} title="Scan with camera">
        <CameraScanner
          onDetected={(scanned) => {
            setCamera(false);
            void addCode(scanned);
          }}
        />
      </Dialog>
    </>
  );
}

function Cart({
  lines,
  currency,
  lineTotals,
  onChange,
}: {
  lines: CartLine[];
  currency: string;
  lineTotals: string[] | null;
  onChange: (lines: CartLine[]) => void;
}) {
  return (
    <ul aria-label="Cart" className="flex flex-col divide-y divide-slate-100 rounded-2xl bg-white shadow-card ring-1 ring-slate-200">
      {lines.map((line, index) => {
        const problem = quantityProblem(line, line.quantity);
        return (
          <li key={line.productId + line.unitPrice} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{line.name}</p>
              <p className="text-sm text-slate-600">
                <Money amount={line.unitPrice} currency={currency} size="sm" /> {line.allowsFraction ? `per ${line.unitCode.toLowerCase()}` : "each"}
              </p>
              {shortOfStock(line) && (
                <p className="mt-1">
                  <Badge tone="warning">Only {Number(line.onHand)} in stock</Badge>
                </p>
              )}
            </div>
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-1">
                {!line.allowsFraction && (
                  <Button variant="secondary" aria-label={`One less ${line.name}`} onClick={() => onChange(stepQuantity(lines, index, -1))} className="px-3">
                    <Minus aria-hidden="true" className="size-4" />
                  </Button>
                )}
                <label className="sr-only" htmlFor={`qty-${index}`}>
                  Quantity of {line.name}
                </label>
                <input
                  id={`qty-${index}`}
                  value={line.quantity}
                  inputMode="decimal"
                  onChange={(e) => onChange(setQuantity(lines, index, e.target.value.trim()))}
                  aria-invalid={Boolean(problem)}
                  aria-describedby={problem ? `qty-${index}-error` : undefined}
                  className="tabular min-h-11 w-20 rounded-lg border border-slate-300 text-center text-base font-semibold focus:border-emerald-600 focus:outline-none focus:ring-4 focus:ring-emerald-600/15 aria-[invalid=true]:border-red-700"
                />
                {line.allowsFraction ? (
                  <span className="text-sm text-slate-600">{line.unitCode.toLowerCase()}</span>
                ) : (
                  <Button variant="secondary" aria-label={`One more ${line.name}`} onClick={() => onChange(stepQuantity(lines, index, 1))} className="px-3">
                    <Plus aria-hidden="true" className="size-4" />
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-1">
                <span className="w-28 text-right">
                  <Money amount={lineTotals?.[index] ?? null} currency={currency} />
                </span>
                <Button variant="ghost" aria-label={`Remove ${line.name}`} onClick={() => onChange(removeLine(lines, index))} className="px-3">
                  <Trash2 aria-hidden="true" className="size-4" />
                </Button>
              </div>
            </div>
            {problem && (
              <p id={`qty-${index}-error`} className="text-sm font-medium text-red-700 sm:basis-full">
                {problem}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function SaleComplete({ sale, storeId, onNext }: { sale: Sale; storeId: string; onNext: () => void }) {
  const next = useRef<HTMLButtonElement>(null);
  useEffect(() => next.current?.focus(), []);
  const change = Number(sale.change_given) > 0;
  return (
    <section aria-labelledby="done-heading" className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl bg-white p-8 text-center shadow-card ring-1 ring-slate-200">
      <CircleCheck aria-hidden="true" className="size-12 text-emerald-600" />
      <div>
        <h2 id="done-heading" className="text-xl font-semibold">
          Sale complete
        </h2>
        <p className="tabular mt-1 font-mono text-sm text-slate-600">{sale.receipt_number}</p>
      </div>
      {change ? (
        <div role="status" className="rounded-xl bg-emerald-50 px-6 py-4 ring-1 ring-emerald-600/20">
          <p className="text-sm font-medium text-emerald-900">Change to give</p>
          <Money amount={sale.change_given} currency={sale.currency} size="display" />
        </div>
      ) : (
        <p role="status" className="text-slate-700">
          Total <Money amount={sale.total} currency={sale.currency} size="lg" />
        </p>
      )}
      {Number(sale.amount_on_credit) > 0 && sale.customer && (
        <p className="text-sm text-amber-900">
          <Money amount={sale.amount_on_credit} currency={sale.currency} size="sm" /> on {sale.customer.name}’s account
        </p>
      )}
      <div className="mt-2 flex w-full flex-col gap-2 sm:flex-row">
        <Link
          href={`/sales/${sale.id}/receipt?store=${storeId}&print=1`}
          className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
        >
          <Printer aria-hidden="true" className="size-4" /> Print receipt
        </Link>
        <Button ref={next} className="flex-1" onClick={onNext}>
          Next sale
        </Button>
      </div>
      <p className="text-xs text-slate-600">Or just scan the next item.</p>
    </section>
  );
}
