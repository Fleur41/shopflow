import { createHmac } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PASSWORD = "e2e-shop-password-2026";
const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

/** WCAG 2.1 A/AA audit of the current page; any violation fails the test. */
export async function expectAccessible(page: Page, context: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(summary, `Accessibility violations on ${context}`).toEqual([]);
}

/** Collect Content-Security-Policy violations reported in the browser console. */
export function watchCsp(page: Page): string[] {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy/i.test(message.text())) {
      violations.push(message.text());
    }
  });
  return violations;
}

export const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;

/** RFC 6238 code, as an authenticator app would show it (offset in seconds). */
export function totp(base32Secret: string, offsetSeconds = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of base32Secret.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor((Date.now() / 1000 + offsetSeconds) / 30)));
  const hmac = createHmac("sha1", key).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 0xf;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

/** The link in the newest email to ``to`` whose body contains ``path`` (polls Mailpit). */
export async function emailedLink(request: APIRequestContext, to: string, path: string): Promise<string> {
  for (let attempt = 0; attempt < 40; attempt++) {
    const search = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`);
    const messages = ((await search.json()) as { messages: { ID: string }[] }).messages;
    for (const { ID } of messages) {
      const message = (await (await request.get(`${MAILPIT}/api/v1/message/${ID}`)).json()) as { Text: string };
      const match = message.Text.match(new RegExp(`https?://\\S+${path}\\?token=[A-Za-z0-9_-]+`));
      if (match) return new URL(match[0]).pathname + new URL(match[0]).search;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`No email with ${path} sent to ${to}`);
}

export async function signUpOwner(page: Page, id: string, name = "Ada Wanjiru") {
  const email = `owner-${id}@e2e.example`;
  await page.goto("/signup");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByLabel("Business name").fill(`Duka ${id}`);
  await page.getByLabel("First shop name").fill("Kawangware");
  await page.getByRole("button", { name: "Create my business" }).click();
  await expect(page.getByRole("heading", { name: `Welcome, ${name.split(" ")[0]}` })).toBeVisible();
  return email;
}

/** Turn on two-step verification from the account page; returns the secret. */
export async function enableTwoStep(page: Page): Promise<string> {
  await page.goto("/account");
  await page.getByRole("button", { name: "Set up two-step verification" }).click();
  const secret = (await page.getByTestId("totp-secret").textContent())!.trim();
  await page.getByLabel("Verification code").fill(totp(secret));
  await page.getByRole("button", { name: "Turn on two-step verification" }).click();
  await expect(page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
  await page.getByRole("button", { name: "I’ve saved them" }).click();
  return secret;
}

export async function signOut(page: Page, name: string) {
  await page.getByText(name).first().click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
}
