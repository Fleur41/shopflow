import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

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
