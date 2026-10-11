# ShopFlow — Pricing algorithm (v1)

The single definition of how a cart's totals are computed (ADR-17). The server
(`backend/apps/sales/pricing.py`) is authoritative; the web
(`frontend/src/lib/pricing.ts`) and Android clients implement the same steps
for display. All of them must pass `shared/pricing-test-vectors/v1.json` in CI.
Change the algorithm only together with the vectors and every implementation.

## Inputs

| Field | Format | Rules |
|---|---|---|
| `minor_units` | integer | Decimal places of the currency: 2 for KES, 0 for UGX. 0–4. |
| `tax_mode` | `INCLUSIVE` \| `EXCLUSIVE` | Whether prices already contain tax (Q-1: Kenyan default is `INCLUSIVE`). |
| `lines[].quantity` | decimal string, ≤ 3 places | > 0 |
| `lines[].unit_price` | decimal string, ≤ 4 places | ≥ 0 |
| `lines[].discount_amount` | decimal string, ≤ `minor_units` places | Optional, default 0. Absolute amount off the line; ≤ the line's gross amount. |
| `lines[].tax_rate` | decimal string, ≤ 4 places | A fraction, 0 ≤ rate < 1 (0.16 is 16 %). |
| `order_discount` | decimal string, ≤ `minor_units` places | Optional, default 0. ≤ the sum of the lines after their own discounts. |

Decimal strings are plain digits with an optional fraction (`"12"`, `"0.5"`): no
sign, exponent or spaces. Amounts are never floats.

## Steps

All arithmetic is exact (integers or rationals). Rounding is **half up** to the
currency's minor unit, and happens only where stated.

1. **Gross:** `gross = round(quantity × unit_price)`.
2. **Line discount:** `net = gross − discount_amount`.
3. **Order discount** is split across lines in proportion to `net`, in minor
   units, by largest remainder: each line gets `floor(order_discount × net / Σnet)`;
   the units left over go one each to the lines with the largest remainders,
   ties to the earlier line. The shares add up exactly to `order_discount`.
4. **Taxable amount:** `amount = net − order_discount_share`. This is in the
   prices' tax mode.
5. **Tax**, rounded per line:
   - `INCLUSIVE`: `tax = round(amount × rate / (1 + rate))`, `line_total = amount`
   - `EXCLUSIVE`: `tax = round(amount × rate)`, `line_total = amount + tax`
6. **Totals:**
   - `subtotal = Σgross`
   - `discount_total = Σdiscount_amount + order_discount`
   - `tax_total = Σtax`
   - `total = Σline_total`
   - `taxes`: one entry per distinct rate, ascending, with `taxable_amount =
     Σ(line_total − tax)` and `tax_amount = Σtax`. Receipts and eTIMS use this
     breakdown.

Every output amount is a string with exactly `minor_units` decimal places.

## Errors

A calculation is refused at the first problem found, checking the settings, then each line in order (its fields, then its rules), then the order discount. `line` (0-based) says which line, where it applies:

| Code | When |
|---|---|
| `INVALID_NUMBER` | Not a plain decimal string (includes negatives) |
| `TOO_MANY_DECIMALS` | More decimal places than the field allows |
| `INVALID_SETTINGS` | `minor_units` outside 0–4, or an unknown `tax_mode` |
| `QUANTITY_NOT_POSITIVE` | Quantity is 0 |
| `INVALID_TAX_RATE` | Rate is 1 or more |
| `LINE_DISCOUNT_EXCEEDS_LINE` | `discount_amount > gross` |
| `ORDER_DISCOUNT_EXCEEDS_TOTAL` | `order_discount > Σnet` |

Who may give a discount, and how much, is a permission rule checked by the
sale service (Q-9), not part of this calculation.
