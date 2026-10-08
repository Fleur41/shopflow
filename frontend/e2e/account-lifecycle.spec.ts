import { expect, test } from "@playwright/test";

import { emailedLink, enableTwoStep, expectAccessible, PASSWORD, signOut, signUpOwner, totp, unique } from "./helpers";

test("an owner with two-step verification signs in with a code", async ({ page }) => {
  const email = await signUpOwner(page, unique(), "Neema Otieno");
  const secret = await enableTwoStep(page);
  await signOut(page, "Neema Otieno");

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-step verification" })).toBeVisible();
  await expectAccessible(page, "sign-in code step");

  await page.getByLabel("Verification code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Code not accepted" })).toBeVisible();

  // The setup code's time step is used up; an app shows the next one soon after.
  await page.getByLabel("Verification code").fill(totp(secret, 30));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Neema" })).toBeVisible();
  await expect(page.getByText("Protect your business with two-step verification")).toHaveCount(0);
});

test("a forgotten password is reset through an emailed link", async ({ page, request }) => {
  const email = await signUpOwner(page, unique(), "Baraka Mwangi");
  await signOut(page, "Baraka Mwangi");

  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expectAccessible(page, "forgot password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

  await page.goto(await emailedLink(request, email, "/reset-password"));
  await expectAccessible(page, "reset password");
  await page.getByLabel(/^New password/).fill("a-fresh-shop-password");
  await page.getByLabel("Repeat new password").fill("a-fresh-shop-password");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("heading", { name: "Password changed" })).toBeVisible();

  await page.getByRole("link", { name: "Sign in" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("a-fresh-shop-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Baraka" })).toBeVisible();
});

test("an invited person creates their account and joins the business", async ({ page, request, browser }) => {
  const id = unique();
  await signUpOwner(page, id, "Zawadi Kamau");
  await enableTwoStep(page);
  const invitee = `invitee-${id}@e2e.example`;

  await page.goto("/settings/staff");
  await page.getByRole("button", { name: "Invite by email" }).click();
  const dialog = page.getByRole("dialog", { name: "Invite by email" });
  await dialog.getByLabel("Email").fill(invitee);
  await dialog.getByLabel("MAIN · Kawangware").check();
  await dialog.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByRole("heading", { name: "Pending invitations" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: invitee })).toBeVisible();

  const link = await emailedLink(request, invitee, "/accept-invite");
  const inviteeBrowser = await browser.newContext();
  const inviteePage = await inviteeBrowser.newPage();
  await inviteePage.goto(link);
  await expect(inviteePage.getByRole("heading", { name: `Join Duka ${id}` })).toBeVisible();
  await expectAccessible(inviteePage, "accept invitation");
  await inviteePage.getByLabel("Your name").fill("Imani Wekesa");
  await inviteePage.getByLabel("Choose a password").fill(PASSWORD);
  await inviteePage.getByRole("button", { name: `Join Duka ${id}` }).click();
  await expect(inviteePage.getByRole("heading", { name: "Welcome, Imani" })).toBeVisible();
  await expect(inviteePage.getByText("You’re working in Kawangware (MAIN).")).toBeVisible();
  await inviteeBrowser.close();

  await page.reload();
  await expect(page.getByRole("row", { name: /Imani Wekesa/ })).toContainText("Cashier");
  await expect(page.getByRole("heading", { name: "Pending invitations" })).toHaveCount(0);
});
