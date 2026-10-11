import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PaymentMethod } from "@/lib/api/types";

import { AddPaymentMethodForm, EditPaymentMethodForm } from "./PaymentMethodForms";

const json = (status: number, body: object) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/** Answers every request with ``response`` and records the bodies sent. */
function stubFetch(response: () => Response) {
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (input: Request) => {
    bodies.push(JSON.parse(await input.clone().text()));
    return response();
  });
  return bodies;
}

const MPESA: PaymentMethod = {
  id: "0192f0aa-0000-7000-8000-000000000001",
  code: "MPESA",
  name: "M-Pesa",
  kind: "MOBILE_MONEY",
  provider: "MANUAL",
  requires_reference: true,
  position: 2,
  etims_payment_type: "06",
  is_active: true,
  version: 3,
  created_at: "2026-10-11T08:00:00Z",
  updated_at: "2026-10-11T08:00:00Z",
};

beforeEach(() => {
  document.cookie = "csrftoken=t";
});
afterEach(() => vi.unstubAllGlobals());

describe("AddPaymentMethodForm", () => {
  it("lets the server choose the eTIMS type and suggests a reference by kind", async () => {
    const bodies = stubFetch(() => json(201, { ...MPESA, code: "CHEQUE" }));
    const onDone = vi.fn();
    renderWithClient(<AddPaymentMethodForm onDone={onDone} />);

    await userEvent.type(screen.getByLabelText(/^Name/), "Cheque");
    await userEvent.type(screen.getByLabelText(/^Code/), "cheque");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "OTHER");
    expect(screen.getByLabelText("Cashier must enter a reference")).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Add payment method" }));

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(bodies[0]).toEqual({ code: "cheque", name: "Cheque", kind: "OTHER", requires_reference: false });
  });

  it("shows field errors next to their fields", async () => {
    stubFetch(() =>
      json(400, {
        status: 400,
        code: "VALIDATION_ERROR",
        detail: "One or more fields are invalid.",
        errors: [{ pointer: "/kind", code: "TAKEN", detail: "This business already has a cash payment method." }],
      }),
    );
    renderWithClient(<AddPaymentMethodForm onDone={vi.fn()} />);

    await userEvent.selectOptions(screen.getByLabelText("Kind"), "CASH");
    await userEvent.click(screen.getByRole("button", { name: "Add payment method" }));

    expect(await screen.findByText("This business already has a cash payment method.")).toBeInTheDocument();
    expect(screen.getByLabelText("Kind")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("EditPaymentMethodForm", () => {
  it("sends the version it was opened with", async () => {
    const bodies = stubFetch(() => json(200, { ...MPESA, name: "M-Pesa Till", version: 4 }));
    const onDone = vi.fn();
    renderWithClient(<EditPaymentMethodForm method={MPESA} onDone={onDone} />);

    await userEvent.clear(screen.getByLabelText(/^Name/));
    await userEvent.type(screen.getByLabelText(/^Name/), "M-Pesa Till");
    await userEvent.click(screen.getByLabelText("Active"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(bodies[0]).toMatchObject({ name: "M-Pesa Till", is_active: false, position: 2, version: 3 });
  });

  it("explains when someone else changed the method first", async () => {
    stubFetch(() =>
      json(409, { status: 409, code: "STALE_VERSION", detail: "Someone else changed this. Reload and try again." }),
    );
    const onDone = vi.fn();
    renderWithClient(<EditPaymentMethodForm method={MPESA} onDone={onDone} />);

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Someone else changed this payment method");
    expect(alert).toHaveTextContent("Reload and try again.");
    expect(onDone).not.toHaveBeenCalled();
  });
});
