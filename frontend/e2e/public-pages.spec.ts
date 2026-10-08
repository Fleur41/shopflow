import { expect, test } from "@playwright/test";

import { expectAccessible, watchCsp } from "./helpers";

test("sign-in page is accessible and protected by a nonce-based CSP", async ({ page }) => {
  const csp = watchCsp(page);
  const response = await page.goto("/login");

  const policy = response?.headers()["content-security-policy"] ?? "";
  expect(policy).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(policy).toContain("frame-ancestors 'none'");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expectAccessible(page, "/login");
  expect(csp).toEqual([]);
});

test("sign-up page is accessible", async ({ page }) => {
  await page.goto("/signup");
  await expect(page.getByRole("heading", { name: "Register your business" })).toBeVisible();
  await expectAccessible(page, "/signup");
});

test("signed-out visitors are sent to sign in, keeping where they were going", async ({ page }) => {
  await page.goto("/settings/stores");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings%2Fstores$/);
});

test("wrong credentials show a clear message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("nobody@e2e.example");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  // Next.js adds its own (empty) role="alert" route announcer, so match by text.
  await expect(page.getByRole("alert").filter({ hasText: "Couldn't sign you in" })).toContainText(
    "The email or password is incorrect.",
  );
});
