import { describe, expect, it } from "vitest";

import type { Me } from "./api/types";
import { navItemsFor } from "./nav";

function me(permissions: string[]): Me {
  return {
    user: { id: "u1", email: "a@b.co", full_name: "A", phone: "", email_verified: false },
    organization: null,
    access: {
      role: { id: "r1", name: "Role", template: "CUSTOM" },
      permissions,
      all_stores: true,
      stores: [],
    },
    organizations: [],
  } as unknown as Me;
}

describe("navItemsFor", () => {
  it("shows a cashier only what they may open", () => {
    expect(navItemsFor(me(["stores.view", "sales.create"])).map((i) => i.label)).toEqual(["Dashboard", "Sell", "Stores"]);
  });

  it("shows owners every section", () => {
    expect(navItemsFor(me(["stores.view", "users.view", "roles.view"])).map((i) => i.label)).toEqual([
      "Dashboard",
      "Stores",
      "Staff",
      "Roles",
    ]);
  });
});
