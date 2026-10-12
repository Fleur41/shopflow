import { expect, type Page, test } from "@playwright/test";

import { enableTwoStep, expectAccessible, signUpOwner, unique, watchCsp } from "./helpers";

/** A USB scanner types the code in a few milliseconds and presses Enter. */
async function scan(page: Page, code: string) {
  await page.getByRole("heading", { name: "Sell" }).click(); // focus away from any text field
  await page.keyboard.type(code, { delay: 5 });
  await page.keyboard.press("Enter");
}

async function addProduct(page: Page, name: string, price: string, barcode: string) {
  await page.goto("/products");
  await page.getByRole("button", { name: "Add product" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a product" });
  await dialog.getByLabel(/^Name/).fill(name);
  await dialog.getByLabel(/^Selling price/).fill(price);
  await dialog.getByLabel(/^Unit/).selectOption({ label: "Pieces (PCS)" });
  await dialog.getByLabel(/^Tax rate/).selectOption({ label: "VAT 16% (16%)" });
  await dialog.getByLabel(/^Barcode/).fill(barcode);
  await dialog.getByRole("button", { name: "Add product" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
}

async function openingStock(page: Page, name: string, quantity: string) {
  await page.goto("/inventory");
  await page.getByRole("button", { name: `Adjust ${name}` }).click();
  const dialog = page.getByRole("dialog", { name: `Adjust ${name}` });
  await expect(dialog.getByLabel("Reason")).toHaveValue("OPENING_BALANCE");
  await dialog.getByLabel(/How many do you have/).fill(quantity);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
}

test("a cashier scans, takes cash and M-Pesa, prints a receipt and sells on credit", async ({ page }) => {
  const csp = watchCsp(page);
  await signUpOwner(page, unique());
  await enableTwoStep(page); // stock adjustments are a sensitive permission

  await test.step("set up stock", async () => {
    await addProduct(page, "Milk 500ml", "80", "6161100000124");
    await addProduct(page, "Bread 400g", "60", "6161100000131");
    await openingStock(page, "Milk 500ml", "10");
    await openingStock(page, "Bread 400g", "4");
    await expect(page.getByRole("row", { name: /Bread 400g/ })).toContainText("4");
    await expectAccessible(page, "stock");
  });

  await test.step("scan and pay cash with change", async () => {
    await page.goto("/sell");
    await expect(page.getByRole("heading", { name: "Sell" })).toBeVisible();
    await scan(page, "6161100000124");
    await scan(page, "6161100000124");
    await scan(page, "6161100000131");
    const cart = page.getByRole("list", { name: "Cart" });
    await expect(cart.getByRole("listitem")).toHaveCount(2);
    await expect(cart.getByLabel("Quantity of Milk 500ml")).toHaveValue("2");
    await expect(page.getByRole("complementary", { name: "Sale total" })).toContainText("220.00");
    await expectAccessible(page, "till");

    await page.keyboard.press("F8");
    const pay = page.getByRole("dialog", { name: "Take payment" });
    await expect(pay.getByRole("button", { name: "Complete sale" })).toBeDisabled();
    await expectAccessible(page, "payment dialog");
    await pay.getByRole("button", { name: "Cash" }).click();
    await pay.getByLabel("Cash given").fill("500");
    await expect(pay).toContainText("Change");
    await pay.getByRole("button", { name: "Complete sale" }).click();

    const done = page.getByRole("region", { name: "Sale complete" });
    await expect(done).toContainText("Change to give");
    await expect(done).toContainText("280.00");
    await expect(done).toContainText(/MAIN-\d{4}-000001/);
  });

  await test.step("the receipt", async () => {
    await page.getByRole("link", { name: "Print receipt" }).click();
    const receipt = page.getByRole("article", { name: /Receipt MAIN-/ });
    await expect(receipt).toContainText("Milk 500ml");
    await expect(receipt).toContainText("2 x 80.00");
    await expect(receipt).toContainText("TOTAL KES");
    await expect(receipt).toContainText("Change");
    await expect(receipt).toContainText("VAT 16% on");
    await page.getByRole("button", { name: "58 mm" }).click();
    await expect(receipt).toHaveClass(/receipt-58/);
  });

  await test.step("stock went down, with the sale in the history", async () => {
    await page.goto("/inventory");
    await expect(page.getByRole("row", { name: /Bread 400g/ })).toContainText("3");
    await page.getByRole("link", { name: "Milk 500ml" }).click();
    await expect(page.getByText("Sale MAIN-")).toBeVisible();
  });

  await test.step("split between cash and M-Pesa", async () => {
    await page.goto("/sell");
    await scan(page, "6161100000131");
    await scan(page, "6161100000131"); // 120.00
    await page.getByRole("button", { name: /^Charge/ }).first().click();
    const pay = page.getByRole("dialog", { name: "Take payment" });
    await pay.getByRole("button", { name: "Cash" }).click();
    await pay.getByLabel("Amount").first().fill("20.00");
    await pay.getByRole("button", { name: "M-Pesa" }).click();
    await expect(pay.getByRole("button", { name: "Complete sale" })).toBeDisabled(); // no code yet
    await pay.getByLabel("M-Pesa code").fill("sk7abc12de");
    await pay.getByRole("button", { name: "Complete sale" }).click();
    await expect(page.getByRole("region", { name: "Sale complete" })).toContainText("000002");
  });

  await test.step("sell on credit to a customer, then they pay by M-Pesa", async () => {
    await page.goto("/customers");
    await page.getByRole("button", { name: "Add customer" }).click();
    const add = page.getByRole("dialog", { name: "Add a customer" });
    await add.getByLabel(/^Name/).fill("Mama Mboga");
    await add.getByLabel("Phone").fill("0712 345 678");
    await add.getByLabel("Credit limit").fill("1000");
    await add.getByRole("button", { name: "Add customer" }).click();
    await expect(page.getByRole("heading", { name: "Mama Mboga" })).toBeVisible();

    await page.goto("/sell");
    await scan(page, "6161100000124"); // 80.00
    await page.keyboard.press("F4");
    const picker = page.getByRole("dialog", { name: "Customer for this sale" });
    await picker.getByLabel("Search customers").fill("0712");
    await picker.getByRole("button", { name: /Mama Mboga/ }).click();
    await page.getByRole("button", { name: /^Charge/ }).first().click();
    const pay = page.getByRole("dialog", { name: "Take payment" });
    await pay.getByRole("button", { name: "On credit" }).click();
    await pay.getByRole("button", { name: "Complete sale" }).click();
    await expect(page.getByRole("region", { name: "Sale complete" })).toContainText("on Mama Mboga’s account");

    await page.goto("/customers");
    await page.getByRole("link", { name: "Mama Mboga" }).click();
    await expect(page.getByRole("region", { name: "Account" })).toContainText("80.00");
    await page.getByRole("button", { name: "Receive payment" }).click();
    const payment = page.getByRole("dialog", { name: "Payment from Mama Mboga" });
    await payment.getByLabel(/^Amount/).fill("50");
    await payment.getByLabel("Paid with").selectOption({ label: "M-Pesa" });
    await payment.getByLabel(/M-Pesa code/).fill("QA12BC34DE");
    await payment.getByRole("button", { name: "Record payment" }).click();
    await expect(payment).toBeHidden();
    await expect(page.getByRole("region", { name: "Account" })).toContainText("30.00");
    await expect(page.getByRole("region", { name: "Statement" })).toContainText("Credit sale");
    await expectAccessible(page, "customer");
  });

  expect(csp).toEqual([]);
});
