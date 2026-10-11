# ShopFlow — KRA eTIMS integration guide

How ShopFlow connects to KRA's Electronic Tax Invoice Management System (eTIMS),
and how a business connects its own eTIMS account to ShopFlow.

- **Part A** is for business owners: what to get from KRA and how to switch eTIMS on.
- **Part B** is for the ShopFlow team: how the integration works and how it gets certified.

Status: **planned** (milestone 3.8, decisions Q-23 and Q-26 to Q-30). The screens in
Part A describe the planned design. Field names come from KRA's *OSCU Specification v2.0*
and *TIS Technical Specification v2.0* (April 2023). Check every detail again in the
KRA sandbox before release, because KRA updates these documents.

---

## What eTIMS means for a shop

Every sale must be sent to KRA and **signed** before the customer gets a receipt. KRA
returns a receipt number, a signature and data for a QR code, and these are printed on the
receipt. Buyers can scan the QR code to check that the invoice is genuine. Business
customers need it to claim the purchase as a business expense or VAT input.

ShopFlow uses KRA's **OSCU** (Online Sales Control Unit) route. ShopFlow's server sends
each sale to KRA over the internet, so stores need no extra device. OSCU needs an
internet connection whenever a receipt is issued (see "When KRA can't be reached").

---

## Part A — Connecting your business

### 1. Before you start

You need:

| What | Where to get it |
|---|---|
| An active **KRA PIN** for the business | [iTax](https://itax.kra.go.ke) |
| The **branch ID** of each shop registered with KRA. The head office is usually `00`; other branches `01`, `02`, … | Your iTax branch registration, or ask KRA. Don't guess: a wrong branch ID is refused. |
| An ID copy of the owner, a director or the legal representative | — |
| KRA's **eTIMS confirmation form**, signed by that person | [eTIMS portal](https://etims.kra.go.ke/main/signup/indexLearnMore) |

### 2. Apply to KRA for system-to-system (OSCU) integration

1. On the [eTIMS taxpayer portal](https://etims.kra.go.ke), sign up for eTIMS and choose
   **System-to-System Integration → OSCU**.
2. Name **ShopFlow** as your invoicing system and integrator. ShopFlow must appear on
   KRA's list of verified eTIMS integrators (Q-27).
3. Register one **device per shop (branch)**. The **device serial number** to use for each
   shop is shown in ShopFlow under *Settings → eTIMS*. (How serial numbers are assigned is
   confirmed in the sandbox; see Q-30.)
4. Submit the ID copy and the signed confirmation form, then wait for KRA's approval.

If you're stuck, contact KRA at callcentre@kra.go.ke or +254 20 4 999 999.

### 3. Switch eTIMS on in ShopFlow

Only the business owner can do this. It needs two-step verification.

1. **Settings → eTIMS → Connect**: enter the business KRA PIN.
2. For each shop, enter its **branch ID** and select **Activate**. ShopFlow contacts KRA and
   shows the taxpayer and branch name that KRA has on record. Check that they're right
   before you confirm.
3. ShopFlow stores the communication key KRA issues for each shop (encrypted). Nobody needs
   to copy or type it.

### 4. Prepare your catalog

KRA needs a few codes for everything you sell. ShopFlow downloads KRA's code lists and
suggests values. You confirm them once.

| In ShopFlow | KRA code | Example |
|---|---|---|
| Each **tax rate** | Tax type A–E | VAT 16 % → **B**; zero-rated → **C**; exempt → **A**; non-VAT → **D**; 8 % → **E** |
| Each **unit of measure** | Quantity unit code | Pieces → `U`, kilograms → `KG`, litres → `LTR` |
| Each **product** | Item classification code, packaging unit, goods or service | Bread → a classification picked from KRA's list, packaging `NT` (net) |
| Each **payment method** | Payment type | Cash `01`, credit `02`, card `05`, M-Pesa `06`, other `07` |

When you save a product, ShopFlow registers it with KRA and reports its opening stock.

### 5. Test, then go live

1. Make a few sales in **training mode**. They print like receipts but say TRAINING, have no
   tax effect and don't count in your totals. Use them to train staff.
2. Make one real sale. Scan the QR code on the receipt with a phone and check that KRA's
   page shows the invoice.

### Day to day

- **Receipts** print only after KRA has signed the sale. Each one shows the *SCU information*
  block: KRA's date and time, CU ID, CU invoice number, internal data, receipt signature and
  the QR code.
- **Buyer's KRA PIN:** enter it when a business customer asks, so they can claim the purchase.
- **Reprints** are copies. They print **COPY** and "THIS IS NOT AN OFFICIAL RECEIPT".
  Only the first print is the original.
- **Voids and returns** produce a **credit note** that refers to the original invoice. Each
  invoice can be cancelled only once. You must give a reason and the name of the person
  receiving the refund.
- **Stock:** eTIMS forbids receipts for goods you don't have in stock. Services are not
  affected. Keep stock accurate: record goods as you receive them.
- **Daily reports:** an X report (since the last Z) at any time, and a Z report per calendar
  day. Both show sales and credit notes by tax type and by payment method.

### When KRA can't be reached

eTIMS forbids issuing a receipt that KRA hasn't signed. If the connection to KRA fails:

1. ShopFlow keeps the sale **on hold**. The stock stays reserved and **no receipt is printed**.
2. The cashier sees "Waiting for KRA" and can retry, or cancel the sale and return the
   customer's money.
3. A banner shows the store is disconnected until KRA answers again. The owner is alerted
   if it lasts more than a few minutes.

For the same reason, the mobile app can't sell offline in a shop with eTIMS switched on
(Q-26).

### Troubleshooting

| Message | What to do |
|---|---|
| "KRA PIN not found" | Check the PIN is active on iTax. |
| "Branch ID invalid" | Confirm the branch ID with KRA. Don't guess. |
| "This device is already installed" (KRA code 902) | The shop was already activated, maybe by another system. Contact ShopFlow support; don't create a new device. |
| "Not a valid device" (901) | The device serial isn't approved for this PIN and branch. Check your KRA application. |
| "Waiting for KRA" doesn't clear | Check the internet connection. If other sites work, KRA may be down: see the status banner, and contact support if it lasts. |

---

## Part B — How the integration works (ShopFlow team)

### Architecture

- `FiscalProvider` interface in `apps/fiscal` with two implementations: `EtimsOscuProvider`
  and `NoFiscalProvider` (businesses without eTIMS). The sale service calls the provider for
  the store, so sales code never depends on eTIMS.
- **Per store:** KRA PIN (org level), `bhf_id`, device serial, and the `cmcKey` (encrypted at
  rest with the existing Fernet key-rotation helper), plus the KRA-side identifiers `sdcId`
  and `mrcNo`.
- **Per sale:** the fiscal state (`PENDING` → `SIGNED`, or `CANCELLED` if never signed), the
  `invcNo` used, the provider that signed it (credit notes must come from the same solution),
  and KRA's response: `curRcptNo`, `totRcptNo`, `intrlData`, `rcptSign`, `sdcDateTime`. The
  signed record is immutable.

### Sale flow with eTIMS (Q-26)

1. The sale service validates and prices the sale, takes the stock locks and commits the sale
   as `PENDING_FISCAL`, with stock reserved and no receipt yet.
2. It calls `saveTrnsSalesOsdc` synchronously, with a short timeout and a few retries.
3. **Signed:** the sale becomes `COMPLETED`, the receipt is rendered with the SCU block, and
   follow-up calls are queued: `insertStockIO` (type `11` sale), then `saveStockMaster`. KRA
   requires that order.
4. **Not signed:** the sale stays pending and the client shows "Waiting for KRA". The cashier
   retries, which resends the same `invcNo`, or cancels, which releases the stock (no credit
   note, because nothing was issued).

Retries must reuse the same `invcNo`. Before relying on it, confirm in the sandbox how KRA
answers a duplicate (code `994`, "overlapped data") and how to recover the signature of an
invoice KRA already accepted.

### API (OSCU v2.0)

Base URL: test `https://etims-api-sbx.kra.go.ke/etims-api/`, production
`https://etims-api.kra.go.ke/etims-api/`. JSON. Every call identifies the taxpayer with
`tin`, `bhfId` and `cmcKey`, except initialization, which issues the key. Success is
`resultCd = "000"`.

| Endpoint | When ShopFlow calls it |
|---|---|
| `selectInitOsdcInfo` | Activating a store: `{tin, bhfId, dvcSrlNo}` returns the `cmcKey` and the store details |
| `selectCodeList`, `selectItemClsList` | Daily, and on demand: KRA code lists and item classifications (pass the last fetch date) |
| `selectBhfList`, `selectNoticeList`, `selectCustomer` | Branch list, KRA notices, looking up a buyer's PIN |
| `saveItem`, `selectItemList` | Creating or changing a product |
| `saveTrnsSalesOsdc` | Each sale and credit note |
| `insertStockIO`, `saveStockMaster` | After each sale, receipt, adjustment or transfer |
| `selectTrnsPurchaseSalesList`, `insertTrnsPurchase` | Phase 5: fetch invoices that eTIMS suppliers issued to us, confirm purchases |
| `selectImportItemList`, `updateImportItem` | Later: importers |

### Mapping ShopFlow data to `saveTrnsSalesOsdc`

| eTIMS field | From ShopFlow |
|---|---|
| `trdInvcNo` | Our receipt number, e.g. `MAIN-2026-000184` |
| `invcNo` | A gapless numeric sequence per store (branch), separate from our receipt number |
| `orgInvcNo` | `0` for a sale; the original `invcNo` for a credit note |
| `salesTyCd` / `rcptTyCd` | `N`ormal, `C`opy, `T`raining or `P`roforma / `S` sale or `R` credit note |
| `pmtTyCd` | The payment method's eTIMS payment type (mixed tenders: Q-29) |
| `salesSttsCd` | `02` approved; `05` credit note generated |
| `rfdRsnCd` | Credit note reason (`06` refund, `03` damaged, …) |
| `custTin`, `custNm` | The buyer's PIN and name, if given |
| `taxblAmtA`…`E`, `taxRtA`…`E`, `taxAmtA`…`E` | Per tax **type**, from the pricing engine's tax breakdown |
| `itemList[]` | Per line: `itemCd`, `itemClsCd`, `itemNm`, `bcd`, `pkgUnitCd`, `pkg`, `qtyUnitCd`, `qty`, `prc`, `splyAmt`, `dcRt`, `dcAmt`, `taxTyCd`, `taxblAmt`, `taxAmt`, `totAmt` |

KRA amounts have 2 decimal places. KES uses 2, so the pricing engine's amounts go across
unchanged.

**Item codes** (`itemCd`) are unique per taxpayer: country of origin + product type
(1 raw material, 2 finished product, 3 service) + packaging unit + quantity unit + a
7-digit sequence, e.g. `KE2NTBA0000012` (Kenya, finished product, net, barrel, item 12). ShopFlow assigns one when a product is first
registered and never changes it.

### Receipt requirements (TIS §3, §6, §10–14)

- Required content: taxpayer name, PIN and shop address; buyer PIN if given; receipt and
  transaction type; serial number; items with quantity, price and tax label; discounts
  (as negatives); totals before discount, discount, taxable, tax and total; payment
  method; item count; the tax table; the **SCU information** block; and TIS receipt
  number and time.
- **Tax table:** every rate with a value above 0 appears on every receipt, even if unused.
  0 % rates appear only when an item used them.
- **SCU block:** `Date: dd/mm/yyyy Time: hh:mm:ss`; `CU ID`; `CU INVOICE NO.: {sdcId}/{curRcptNo}`;
  internal data and signature in groups of 4 characters separated by dashes.
- **QR code:** KRA's verification link built from the PIN, branch ID and receipt signature.
  Confirm the exact format in the sandbox.
- **KRA logo** on every receipt. Amounts shown with 2 decimal places.
- **One original only.** Copies, training and proforma receipts carry the label as a
  watermark and as text at least twice the size of the amounts, plus "THIS IS NOT AN
  OFFICIAL RECEIPT".
- **Credit notes** print "CREDIT NOTE", the original CU invoice number, negative amounts,
  and come from the same solution that signed the original.

### What eTIMS changes elsewhere in ShopFlow

| Area | Change | Milestone |
|---|---|---|
| Pricing | Tax breakdown grouped by tax **type**, not rate value: exempt (A), zero-rated (C) and non-VAT (D) are all 0 % but are reported separately. Needs pricing vectors v2. | 3.8 |
| Catalog | eTIMS tax type on tax rates; quantity unit on units; classification, packaging unit, product type and `itemCd` on products | 2.2 |
| Payment methods | eTIMS payment type on each method | 3.2 |
| Sales | `PENDING_FISCAL` state; buyer PIN; gapless `invcNo` per store | 3.3, 3.8 |
| Receipts | SCU block, QR, logo, COPY watermark, tax table rules | 3.5, 3.8 |
| Voids and returns | Always a credit note referencing the original; once per invoice; reason and recipient name | 3.6, 3.8 |
| Stock | No negative stock for goods in eTIMS stores (Q-4's `ALLOW_NEGATIVE` is blocked); stock movements reported to KRA | 2.4, 3.8 |
| Reports | Fiscal X and Z reports per calendar day, with NS/NC totals by tax type and payment type, plus copy, training and proforma counts | 3.8 |
| Mobile | No offline selling in eTIMS stores (OSCU is online-only) unless VSCU is adopted | 6.5 |
| Training mode | Training sales and credit notes (`T`) for staff practice | 3.8 |

### Getting certified (Q-27)

From KRA's eTIMS portal:

1. Study the OSCU specification and the TIS technical specification.
2. Register on the sandbox (KRA's *OSCU/VSCU step-by-step sign-up guide*), then build and
   test against it.
3. Apply to KRA's eTIMS Operations office with the *eTIMS Bio Data Form for OSCU and VSCU*
   and the required documents:
   - **as a third-party integrator:** business registration (certificate of incorporation,
     CR12), business permit, directors' IDs, tax compliance certificate, proof of at least
     three qualified technical staff, a notarized solvency declaration, architecture
     documentation, and a read-only CD/DVD with the integration software and all PDFs;
   - **as a self-integrating taxpayer:** tax compliance certificate, proof of three technical
     staff, architecture documentation, and the CD/DVD.
4. KRA runs a technical and administrative review and issues an **interim approval
   certificate**. Live receipts can be issued from then on.
5. When the interim certificate expires, KRA reviews the integration again and issues the
   final certification.

The TIS must show its **software version** to KRA officers, and the version must change with
every software change. ShopFlow's release version and commit already do this; show them in
*Settings → About*.

### Testing

- Unit tests run against **recorded sandbox responses** (success, each error code, timeout,
  duplicate). They never call KRA.
- A tagged suite runs against the live sandbox before each release.
- Concurrency: two cashiers completing sales at once get consecutive `invcNo`s with no gap
  or duplicate.
- Fault injection: KRA times out after receiving the sale. The retry must not create a
  second invoice.

### Sources

- [eTIMS system-to-system integration – KRA](https://www.kra.go.ke/business/etims-electronic-tax-invoice-management-system/learn-about-etims/etims-system-to-system-integration):
  OSCU and VSCU specifications v2.0, the TIS technical specification, the sandbox guide,
  the list of verified integrators
- [eTIMS taxpayer portal – solutions and certification](https://etims.kra.go.ke/main/signup/indexLearnMore)
- [KRA eTIMS service page](https://www.kra.go.ke/services/service/16)
- Sandbox portal: <https://etims-sbx.kra.go.ke/>
