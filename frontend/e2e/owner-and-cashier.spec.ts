import { expect, test } from "@playwright/test";

import { enableTwoStep, expectAccessible, PASSWORD, signOut, signUpOwner, unique, watchCsp } from "./helpers";

// A 1×1 PNG, as a phone or scanner app might upload.
const PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

test("an owner sets up a business; a cashier sees only their store", async ({ page }) => {
  const csp = watchCsp(page);
  const id = unique();
  const cashier = `cashier-${id}@e2e.example`;

  await test.step("owner registers and is prompted to secure the account", async () => {
    await signUpOwner(page, id);
    await expect(page.getByText("You’re working in Kawangware (MAIN).")).toBeVisible();
    await expect(page.getByText("Protect your business with two-step verification")).toBeVisible();
    await expect(page.getByText("Confirm your email address")).toBeVisible();
    await expectAccessible(page, "dashboard");
  });

  await test.step("sensitive actions need two-step verification first", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Stores" }).click();
    await page.getByRole("button", { name: "Add store" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a store" });
    await dialog.getByLabel("Store code").fill("wst");
    await dialog.getByLabel("Store name").fill("Westlands");
    await dialog.getByRole("button", { name: "Add store" }).click();
    await expect(dialog.getByRole("alert").filter({ hasText: "two-step verification" })).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Set up two-step verification" })).toBeVisible();
  });

  await test.step("owner turns on two-step verification", async () => {
    await page.goto("/account");
    await expectAccessible(page, "account");
    await enableTwoStep(page);
    await expect(page.getByText("Signing in needs your password and a code")).toBeVisible();
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
    await expectAccessible(page, "roles");
  });

  await test.step("payment methods start with cash, M-Pesa and card; the owner adds one", async () => {
    await page.getByRole("link", { name: "Payment methods" }).click();
    await expect(page.getByRole("cell", { name: "MPESA" })).toBeVisible();
    await expectAccessible(page, "payment methods");
    await page.getByRole("button", { name: "Add payment method" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a payment method" });
    await dialog.getByLabel(/^Name/).fill("Airtel Money");
    await dialog.getByLabel(/^Code/).fill("airtel");
    await expectAccessible(page, "add-payment-method dialog");
    await dialog.getByRole("button", { name: "Add payment method" }).click();
    await expect(page.getByRole("row", { name: /Airtel Money/ })).toContainText("06 · Mobile money");
  });

  await test.step("the catalog starts with units and Kenya's tax rates", async () => {
    await page.getByRole("link", { name: "Catalog setup" }).click();
    await expect(page.getByRole("row", { name: /VAT 16%/ })).toContainText("B · VAT 16%");
    await expect(page.getByRole("row", { name: /Pieces/ })).toContainText("U");
    await expectAccessible(page, "catalog setup");
  });

  await test.step("the owner adds a product with a barcode, an image and a new price", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Products" }).click();
    await expect(page.getByText("No products yet")).toBeVisible();
    await page.getByRole("button", { name: "Add product" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a product" });
    await dialog.getByLabel(/^Name/).fill("Sugar 1kg");
    await dialog.getByLabel(/^Selling price/).fill("150");
    await dialog.getByLabel(/^Unit/).selectOption({ label: "Kilogram (KG)" });
    await dialog.getByLabel(/^Tax rate/).selectOption({ label: "VAT 16% (16%)" });
    await dialog.getByLabel(/^Barcode/).fill("5901234123457");
    await expectAccessible(page, "add-product dialog");
    await dialog.getByRole("button", { name: "Add product" }).click();

    await expect(page.getByRole("heading", { name: "Sugar 1kg" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Barcodes and codes" })).toContainText("5901234123457");

    await page.getByLabel("Upload image").setInputFiles({ name: "sugar.png", mimeType: "image/png", buffer: Buffer.from(PNG_1PX, "base64") });
    const image = page.getByRole("img", { name: "Sugar 1kg" });
    await expect(image).toHaveAttribute("src", /^http:\/\/localhost:8000\/media\/products\/.+\.webp$/);
    // Loaded, so the page's CSP allows the media origin and the file is served.
    await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0);

    await page.getByLabel(/^Selling price/).fill("155");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("region", { name: "Price history" })).toContainText(/150\.00.*→.*155\.00/);
    await expectAccessible(page, "product page");
  });

  await test.step("the owner adds a supplier and makes it the product's preferred source", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Suppliers" }).click();
    await expect(page.getByText("No suppliers yet")).toBeVisible();
    await page.getByRole("button", { name: "Add supplier" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a supplier" });
    await dialog.getByLabel(/^Name/).fill("Mumias Sugar");
    await dialog.getByLabel("Phone").fill("+254 712 345 678");
    await dialog.getByLabel("KRA PIN").fill("p051234567x");
    await dialog.getByLabel("Payment terms (days)").fill("30");
    await expectAccessible(page, "add-supplier dialog");
    await dialog.getByRole("button", { name: "Add supplier" }).click();

    await expect(page.getByRole("heading", { name: "Mumias Sugar" })).toBeVisible();
    await expect(page.getByText("KRA P051234567X")).toBeVisible();
    await expect(page.getByText("30 days")).toBeVisible();

    const contacts = page.getByRole("region", { name: "Contacts" });
    await contacts.getByLabel(/^Contact name/).fill("Wanjiku Kamau");
    await contacts.getByLabel("Role").fill("Sales rep");
    await contacts.getByRole("button", { name: "Add contact" }).click();
    await expect(contacts).toContainText("Primary");

    const supplied = page.getByRole("region", { name: "Products supplied" });
    await supplied.getByLabel("Link a product").fill("sugar");
    await supplied.getByRole("button", { name: /Sugar 1kg/ }).click();
    await supplied.getByLabel("Minimum order").fill("50");
    await supplied.getByLabel("Lead time (days)").fill("3");
    await supplied.getByRole("button", { name: "Link product" }).click();
    await expect(supplied).toContainText("Preferred");
    await expect(supplied).toContainText("Min. order 50 · 3-day lead time");
    await expectAccessible(page, "supplier page");

    await supplied.getByRole("link", { name: "Sugar 1kg" }).click();
    await expect(page.getByRole("region", { name: "Suppliers" })).toContainText("Mumias Sugar");
    await expect(page.getByRole("region", { name: "Suppliers" })).toContainText("Preferred");
  });

  await test.step("a typo still finds the product", async () => {
    await page.getByRole("link", { name: "All products" }).click();
    await page.getByLabel("Search products").fill("suger");
    await expect(page.getByRole("link", { name: "Sugar 1kg" })).toBeVisible();
    await expectAccessible(page, "products");
  });

  await test.step("cashier signs in and sees only their store and sections", async () => {
    await signOut(page, "Ada Wanjiru");
    await page.getByLabel("Email").fill(cashier);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Welcome, Juma" })).toBeVisible();
    await expect(page.getByText("You’re working in Westlands (WST).")).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Staff" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Roles" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Payment methods" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Catalog setup" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Suppliers" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Products" })).toBeVisible();
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
