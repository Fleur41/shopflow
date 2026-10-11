import type { EtimsPaymentType, PaymentMethodKind } from "./api/types";

export const KIND_LABELS: Record<PaymentMethodKind, string> = {
  CASH: "Cash",
  CARD: "Card",
  MOBILE_MONEY: "Mobile money",
  BANK_TRANSFER: "Bank transfer",
  OTHER: "Other",
};

/** KRA eTIMS payment types a payment method can have (docs/ETIMS.md). */
export const ETIMS_LABELS: Record<EtimsPaymentType, string> = {
  "01": "01 · Cash",
  "04": "04 · Bank cheque",
  "05": "05 · Debit or credit card",
  "06": "06 · Mobile money",
  "07": "07 · Other",
};

/** Kinds where the cashier usually types a reference, such as an M-Pesa code. */
export function usuallyNeedsReference(kind: PaymentMethodKind): boolean {
  return kind === "MOBILE_MONEY" || kind === "BANK_TRANSFER";
}
