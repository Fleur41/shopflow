import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "./LoginForm";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams("next=//evil.example"),
}));

const json = (status: number, body: object) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LoginForm />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  document.cookie = "csrftoken=t";
  replace.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("LoginForm", () => {
  it("shows the server's message when sign-in fails", async () => {
    vi.stubGlobal("fetch", async () =>
      json(401, { status: 401, code: "INVALID_CREDENTIALS", detail: "The email or password is incorrect." }),
    );
    renderForm();

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The email or password is incorrect.");
    expect(replace).not.toHaveBeenCalled();
  });

  it("marks invalid fields and links their messages for screen readers", async () => {
    vi.stubGlobal("fetch", async () =>
      json(400, {
        status: 400,
        code: "VALIDATION_ERROR",
        detail: "One or more fields are invalid.",
        errors: [{ pointer: "/email", code: "INVALID", detail: "Enter a valid email address." }],
      }),
    );
    renderForm();

    await userEvent.type(screen.getByLabelText(/password/i), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const email = screen.getByLabelText(/email/i);
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("Enter a valid email address.");
  });

  it("ignores an off-site ?next= and lands on the dashboard", async () => {
    const me = {
      user: { id: "u", email: "a@b.co", full_name: "A", phone: "", email_verified: false },
      organization: { id: "o", name: "Duka" },
      access: null,
      organizations: [],
    };
    vi.stubGlobal("fetch", async (input: Request) =>
      new URL(input.url).pathname === "/api/v1/auth/me/" ? json(200, me) : json(200, { user: me.user }),
    );
    renderForm();

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
    await userEvent.type(screen.getByLabelText(/password/i), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("asks for an authenticator code when two-step verification is on", async () => {
    const me = {
      user: { id: "u", email: "a@b.co", full_name: "A", phone: "", email_verified: true, mfa_enabled: true },
      organization: { id: "o", name: "Duka" },
      access: null,
      organizations: [],
      mfa_verified: true,
    };
    const seen: string[] = [];
    vi.stubGlobal("fetch", async (input: Request) => {
      const path = new URL(input.url).pathname;
      seen.push(path);
      if (path === "/api/v1/auth/login/") {
        return json(401, { status: 401, code: "MFA_REQUIRED", detail: "Enter the code.", mfa_token: "challenge-1" });
      }
      if (path === "/api/v1/auth/mfa/verify/") {
        const body = (await input.json()) as { mfa_token: string; code: string };
        expect(body).toMatchObject({ mfa_token: "challenge-1", code: "123456", client: "web" });
        return json(200, { user: me.user });
      }
      return json(200, me);
    });
    renderForm();

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
    await userEvent.type(screen.getByLabelText(/password/i), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Two-step verification" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // not shown as an error

    await userEvent.type(screen.getByLabelText(/verification code/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(seen).toContain("/api/v1/auth/mfa/verify/");
  });
});
