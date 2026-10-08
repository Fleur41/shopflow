import { describe, expect, it } from "vitest";

import type { Me } from "./api/types";
import { landingPath, needsTwoStep } from "./auth";

const me = (overrides: Partial<Me>) =>
  ({
    user: { id: "u", email: "a@b.co", full_name: "A", phone: "", email_verified: true, mfa_enabled: false },
    organization: { id: "o", name: "Duka" },
    access: { role: { id: "r", name: "Owner", template: "OWNER" }, permissions: [], all_stores: true, stores: [] },
    organizations: [],
    mfa_verified: false,
    ...overrides,
  }) as unknown as Me;

describe("landingPath", () => {
  it("goes where the user was heading", () => {
    expect(landingPath(me({}), "/settings/staff")).toBe("/settings/staff");
  });

  it("asks users with several businesses to choose one", () => {
    expect(landingPath(me({ organization: null }), "/")).toBe("/select-business");
  });

  it("lets pages that need no business (like invitations) through", () => {
    expect(landingPath(me({ organization: null }), "/accept-invite?token=x")).toBe("/accept-invite?token=x");
  });
});

describe("needsTwoStep", () => {
  it("prompts owners and managers until their session is verified", () => {
    expect(needsTwoStep(me({}))).toBe(true);
    expect(needsTwoStep(me({ mfa_verified: true }))).toBe(false);
  });

  it("does not nag cashiers", () => {
    const cashier = me({
      access: { role: { id: "r", name: "Cashier", template: "CASHIER" }, permissions: [], all_stores: false, stores: [] },
    } as Partial<Me>);
    expect(needsTwoStep(cashier)).toBe(false);
  });
});
