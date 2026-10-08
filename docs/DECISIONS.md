# ShopFlow — Decision Log (requirement ambiguities)

The spec (§52) asks that ambiguous business behaviour be identified rather than assumed. Each item below records the default chosen.

**Status: all defaults ACCEPTED on 2026-10-08.** Q-20 (cash sessions) is adopted into scope as milestone 3.7. To change a decision, update this table and the affected ADR in the same pull request.

| # | Question | Decision | Why | Blocks |
|---|---|---|---|---|
| Q-1 | Market, currency and tax regime? | Kenya-first assumptions (KES, VAT 16 %, **tax-inclusive** shelf prices) as **org-level configuration**, never hard-coded. One currency per store. | The examples use +254 and M-Pesa. Retail shelf prices in Kenya are normally VAT-inclusive. | Phase 3 |
| Q-2 | Can quantities be fractional (sugar by kg, fabric by metre)? | **Yes**, `numeric(14,3)`, allowed only for units marked `allows_fraction`. | Common in small shops. Retrofitting decimals later is costly. | Phase 2 |
| Q-3 | Are customers shared across all stores of an organization, or per store? | **Organization-level** customers with one account (ledger) per currency. Ledger entries record which store they came from. Cashiers see customers org-wide; contact details depend on permission. | A customer who buys at two branches should have one balance. The spec diagram places customers under Store; this departs from it on purpose. | Phase 4 |
| Q-4 | An **offline** sale syncs, but the server shows insufficient stock. What happens? | Store setting, default **`QUEUE_FOR_REVIEW`**: the sale is recorded, but the stock-dependent part waits in a conflict queue until a manager resolves it (adjust stock, then accept). Admins can switch a store to **`ALLOW_NEGATIVE`** (audited). | The goods physically left the shop and money was taken, so rejecting the sale would make the books wrong. Rule 3 forbids negative stock unless an admin configured it. | Phase 6 |
| Q-5 | Offline credit sales, when the credit limit can't be checked live? | Allowed up to the **last-synced available credit**. If the server finds the limit exceeded at sync, the sale is accepted and a `CREDIT_LIMIT_EXCEEDED` conflict is raised for review. A store can disable offline credit sales entirely. | Same reasoning as Q-4: the transaction already happened. | Phase 6 |
| Q-6 | Overpayments / customer credit balances? | **Rejected** in the MVP (`PAYMENT_EXCEEDS_BALANCE`). `balance >= 0` is a DB constraint. It could be relaxed later to support store credit. | The spec says to disallow unless explicitly supported. | Phase 4 |
| Q-7 | Price changed between display and checkout? | Online: `409 PRICE_CHANGED`, and the cashier confirms. Offline: the price shown to the customer is honoured and recorded, and differences are flagged in a report (no conflict). | The customer paid the displayed price. Silent repricing would be wrong either way. | Phase 3 |
| Q-8 | Voids vs returns? | **Void** = same business day, `sales.void` permission and a reason, full reversal. **Return** = later, per item, partial allowed, optional restock, refund in cash or to customer credit. Nothing is ever deleted. | Standard retail practice. Meets rules 4–5. | Phase 3 |
| Q-9 | Who can give discounts or override prices? | Cashier: none by default. Manager: up to `max_discount_percent` on their role. Owner: unlimited. Every discount or override needs a reason and is audited. | Discount abuse is a top retail fraud vector. | Phase 3 |
| Q-10 | Inventory valuation method? | **Weighted average cost** per store/product. Each movement records `unit_cost`, and each sale line snapshots cost for margin reports. | FIFO or lot costing is much more complex and rarely needed by small shops. | Phase 5 |
| Q-11 | Receipt number format? | Online: `{STORE}-{YYYY}-{seq:06}` (gapless per store and year). Offline: `{STORE}-{DEVICE}-{seq:06}`. | Unique without coordination. If a tax authority mandates a format (eTIMS), the format is configurable. | Phase 3 |
| Q-12 | Credit terms and "overdue"? | Org default of 30 days, overridable per customer. Aging is computed FIFO (payments settle the oldest charges first). There are no per-invoice allocations in the MVP. | Simple and matches how shopkeepers think about debt. | Phase 4 |
| Q-13 | Do reconciliation adjustments need a second approver? | MVP: a single user with `customers.reconcile` + a mandatory reason + audit. Optional later: maker-checker above a configurable amount. | The spec requires permission, reason and audit; dual control is an enhancement. | Phase 4 |
| Q-14 | iOS: required, and when? | **Android only** in this plan. Domain and sync code stays in pure-Kotlin modules so Kotlin Multiplatform can add iOS later. | The specified libraries (Retrofit, CameraX, WorkManager, Keystore) are Android-only. | Phase 6 |
| Q-15 | Hosting provider and region? | Provider-agnostic containers + managed PostgreSQL with PITR + S3-compatible storage. Recommend a region close to users (e.g. AWS `af-south-1` Cape Town, or EU) subject to data-residency needs. | Latency at the POS plus data protection obligations. | Phase 8 (staging in Phase 1.3) |
| Q-16 | Must customer phone numbers be unique? | **No** (families and shared phones are common). The UI warns about duplicates when creating a customer. | Hard uniqueness would block legitimate cases. | Phase 4 |
| Q-17 | Multiple currencies within one store? | **No**: one currency per store. Organizations may run stores in different currencies, and reports are then grouped per currency (no FX conversion). | Avoids exchange-rate logic until it's needed. | — |
| Q-18 | Receiving more than ordered on a PO? | Rejected by default. The extra quantity can be received as a separate direct receipt. | Keeps PO lines honest. | Phase 5 |
| Q-19 | Audit log and financial record retention? | Retain **7 years**, configurable. Confirm with an accountant against KRA / local law. | Tax record-keeping rules. | Phase 8 |
| Q-20 | **Cash drawer / shift management** (opening float, cash-up, variances) isn't in the spec. Include it? | **Adopted.** Tills, cash sessions, pay-in/pay-out, blind close-out count, variance. See ARCHITECTURE §6.8. | Without it there's no way to reconcile the cash in the drawer against cash sales. In practice that's the most important daily control in a shop. | Phase 3 |
| Q-21 | Batch/lot and expiry-date tracking? | **Not in the MVP.** `EXPIRED` and `DAMAGED` movements are supported; lot tracking is a later extension. | Significant complexity. Needed mainly for pharmacies and food wholesale. | — |
| Q-22 | M-Pesa in the MVP? | Mobile money payments with a **manual transaction code** entry. Daraja API (STK push, C2B confirmation) via the provider interface later. | Spec §44 lists M-Pesa as a future feature. | — |
| Q-23 | eTIMS / fiscal device integration (KRA)? | Not in scope. Receipt numbering and the immutable sale record are designed so it can be added. | Possibly legally required for VAT-registered businesses. **Worth confirming early.** | — |

## Open questions raised during Phase 1.6

| # | Question | Current behaviour | Why it matters | Blocks |
|---|---|---|---|---|
| Q-24 | Do cashiers have email addresses? Many shop staff may only have a phone. | Every account needs an email; owners create staff accounts with an initial password. | If staff lack email, we need phone-number sign-in and/or a quick till PIN, which is common on POS devices. Changes the `User` model and sign-in flow. | 1.8 / 1.9 |
| Q-25 | May an owner add someone who already has a ShopFlow account (e.g. staff working at two shops)? | Refused until invitations exist (1.9). The person must accept, so one business can't silently attach itself to another's account. | Adding them directly would let any business probe accounts and see real names. | 1.9 |

