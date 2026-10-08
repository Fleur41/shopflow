import { expect, test } from "@playwright/test";

import { expectAccessible, unique, watchCsp } from "./helpers";

const PASSWORD = "e2e-shop-password-2026";

test("an owner sets up a business; a cashier sees only their store", async ({ page }) => {
  const csp = watchCsp(page);
  const id = unique();
  const owner = `owner-${id}@e2e.example`;
  const cashier = `cashier-${id}@e2e.example`;

  await test.step("owner registers a business", async () => {
    await page.goto("/signup");
    await page.getByLabel("Your name").fill("Ada Wanjiru");
    await page.getByLabel("Email").fill(owner);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByLabel("Business name").fill(`Ada Duka ${id}`);
    await page.getByLabel("First shop name").fill("Kawangware");
    await page.getByRole("button", { name: "Create my business" }).click();

    await expect(page.getByRole("heading", { name: "Welcome, Ada" })).toBeVisible();
    await expect(page.getByText("You're working in Kawangware (MAIN).")).toBeVisible();
    await expectAccessible(page, "dashboard");
  });

  await test.step("owner opens a second store", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Stores" }).click();
    await expect(page.getByRole("cell", { name: "MAIN" })).toBeVisible();
    await expectAccessible(page, "stores");

    await page.getByRole("button", { name: "Add store" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a store" });
    await expectAccessible(page, "add-store dialog");
    await dialog.getByLabel("Store code").fill("wst");
    await dialog.getByLabel("Store name").fill("Westlands");
    await dialog.getByRole("button", { name: "Add store" }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByRole("cell", { name: "WST" })).toBeVisible();
    await expect(page.getByLabel("Store", { exact: true })).toContainText("WST · Westlands");
  });

  await test.step("owner adds a cashier for Westlands only", async () => {
    await page.getByRole("link", { name: "Staff" }).click();
    await page.getByRole("button", { name: "Add staff" }).click();
    const dialog = page.getByRole("dialog", { name: "Add staff" });
    await dialog.getByLabel("Full name").fill("Juma Ali");
    await dialog.getByLabel("Email").fill(cashier);
    await dialog.getByLabel("Initial password").fill(PASSWORD);
    await dialog.getByLabel("WST · Westlands").check();
    await expectAccessible(page, "add-staff dialog");
    await dialog.getByRole("button", { name: "Add staff" }).click();

    await expect(dialog).toBeHidden();
    const row = page.getByRole("row", { name: /Juma Ali/ });
    await expect(row).toContainText("Cashier");
    await expect(row).toContainText("WST");
    await expectAccessible(page, "staff");
  });

  await test.step("roles are listed with the owner as a system role", async () => {
    await page.getByRole("link", { name: "Roles" }).click();
    await expect(page.getByRole("heading", { name: "Owner" })).toBeVisible();
    await expect(page.getByText("System role")).toBeVisible();
    await expectAccessible(page, "roles");
  });

  await test.step("owner signs out", async () => {
    await page.getByText("Ada Wanjiru").click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  await test.step("cashier signs in and sees only their store and sections", async () => {
    await page.getByLabel("Email").fill(cashier);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByRole("heading", { name: "Welcome, Juma" })).toBeVisible();
    await expect(page.getByText("You're working in Westlands (WST).")).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Staff" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Roles" })).toHaveCount(0);
    await expect(page.getByLabel("Store", { exact: true }).locator("option")).toHaveText(["WST · Westlands"]);
  });

  await test.step("the server refuses what the menu hides", async () => {
    await page.goto("/settings/staff");
    await expect(page.getByRole("alert").filter({ hasText: "Couldn't load staff" })).toContainText(
      "You don't have permission to do this.",
    );
  });

  expect(csp, "CSP violations").toEqual([]);
});
