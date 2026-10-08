# ShopFlow — Development Roadmap

Development proceeds in vertical slices. Each milestone is a set of small pull requests that ends in a demonstrable, tested increment. A milestone is done only when it meets the **Definition of Done** (end of this file).

This follows the phase order in the spec, with three deliberate changes:
1. **CI, security baseline and observability start in Phase 1**, not Phase 8. Phase 8 is hardening, not introduction (spec §33).
2. **Idempotency and audit frameworks are built in Phase 1**, so every later financial endpoint uses them from day one.
3. **Suppliers (basic CRUD) move into Phase 2**, where the spec also lists them. Phase 5 adds purchasing on top.

The sync API contract (`client_txn_id`, `occurred_at`, `origin`) is designed into the sales and payments endpoints from Phase 3, so Phase 6 (mobile) needs no backend rework.

---

## Phase 0 — Design (this deliverable)
- [x] Architecture, ERD, API spec, security model, roadmap, decision log
- [x] Defaults in [DECISIONS.md](DECISIONS.md) accepted (2026-10-08), cash sessions added to scope

## Phase 1 — Foundation

Status: 1.1–1.4 done (2026-10-08), with these adjustments:
- The custom `User` model was pulled forward from 1.5, because Django requires it before the first migration.
- `TenantModel` moves to 1.6. It needs `Organization`; the tenant-independent `BaseModel` (UUIDv7, timestamps) is in place.
- Branch protection on `main` (require CI + one review) must be enabled in the GitHub repository settings by the repo owner.

1.5 done (2026-10-08). Deferred, by dependency:
- Org-scoped sessions (`org` claim, switch-organization) → 1.6, which introduces organizations.
- Emails for lockout and token-reuse alerts → 1.9, which adds email delivery.
- Purging rows of ended sessions → 2.6, which adds Celery beat.
- "Progressive delay" was replaced by the per-email throttle plus lockout, which together bound guessing at 5/min and 10 per 15 min.

1.6 done (2026-10-08), with the 1.7 audit log pulled forward so tenancy changes were audited from the start. 1.7 completed the same day: the idempotency framework (with real-concurrency tests) and separate owner/app database roles.
1.8 done (2026-10-08):
- **Screens:** sign-up, sign-in, business selection, app shell (navigation filtered by permissions, store switcher, sign-out and sign-out-everywhere), dashboard, stores (list and create), staff (list, add, suspend, reactivate), roles (read-only).
- **Platform:** strict nonce CSP (ADR-18), typed API client with CSRF and shared refresh (ADR-19), and a Playwright + axe end-to-end suite in CI.
- **Deferred:** UI to edit roles and members' roles/stores (the API exists), and sign-in by phone or PIN (Q-24).

Deferred:
- PostgreSQL row-level security → 8.1, as planned.

1.9 done (2026-10-08). **Phase 1 is complete.**
- **Email:** delivery via SMTP (Mailpit locally), email verification, password reset and change with email notices.
- **Two-step verification:** TOTP with recovery codes and replay protection, enforced per sensitive action (SECURITY.md §2.4).
- **Invitations**, including for people who already have an account.
- **Web:** pages for all of the above, plus E2E journeys that use real emails from Mailpit and real TOTP codes.
- **Fixed:** a password reset didn't lift an active sign-in lockout.
- **Deferred:** step-up MFA for very sensitive actions → 8.6 (as planned). Regenerating recovery codes without turning MFA off → later.

| # | Milestone | Acceptance criteria |
|---|---|---|
| 1.1 ✅ | Repo skeleton | Monorepo layout. `.gitignore`, `.editorconfig`, pre-commit (ruff, gitleaks), `.env.example`, CONTRIBUTING.md, PR template, CODEOWNERS. |
| 1.2 ✅ | Local environment | `docker compose up` starts PostgreSQL 17, Redis, Django and Next.js with hot reload. `make test` works. README local setup verified from a clean clone. |
| 1.3 ✅ | CI baseline | GitHub Actions: lint (ruff, eslint), types (mypy/django-stubs, `tsc --strict`), tests with PostgreSQL service, coverage report, pip-audit/npm audit, gitleaks, Trivy, Docker build. Branch protection on `main`. |
| 1.4 ✅ | Django core | Split settings, `common` app (`TenantModel`, UUIDv7, money/quantity fields, problem-details error handler, cursor pagination, request-ID middleware, structlog JSON logging with redaction, `/healthz` `/readyz`), Sentry wiring, `check --deploy` clean |
| 1.5 ✅ | Accounts and auth | Custom `User` (email login, Argon2id). Login, refresh with rotation and reuse detection, logout, logout-all, session list and revoke. Cookie transport + CSRF for web, bearer for mobile. Throttles and lockout. Full test coverage of token flows. |
| 1.6 ✅ | Organizations and RBAC | Organization, Store, Membership, MembershipStore, Role, Permission catalog, role templates. Tenant context resolution. Scoped managers. Permission-declaration test. **Cross-tenant BOLA test harness** (parametrized over all routes). Org signup flow creates org, owner and default store. |
| 1.7 ✅ | Audit and idempotency frameworks | `audit_log` (append-only trigger + grants). `record_audit()` service API. Idempotency claim/replay utility with concurrency tests. Two DB roles (migrator/app) in compose and CI. |
| 1.8 ✅ | Web shell | Next.js App Router, TS strict, design system (accessible primitives, e.g. Radix/shadcn), login, org/store switcher, protected layout, API client generated from OpenAPI, error/loading/empty state patterns, Playwright + axe smoke test |
| 1.9 ✅ | Account lifecycle | Email verification, password reset, password change, TOTP MFA (enforced for sensitive roles), member invitation |

**Demo:** sign up a business, invite a cashier limited to one store, and show that the cashier cannot see the other store or another org's data. Every one of those actions is in the audit log.

## Phase 2 — Catalog, suppliers, inventory

| # | Milestone | Acceptance criteria |
|---|---|---|
| 2.1 | Catalog master data | Categories, brands, units (fraction flag), tax rates. CRUD + permissions + audit. |
| 2.2 | Products | Product CRUD, multiple identifiers with uniqueness per org, image upload pipeline, price changes audited with price history, optimistic versioning, trigram search |
| 2.3 | Suppliers | Supplier, contacts, product–supplier links (preferred supplier, supplier SKU, MOQ, lead time) |
| 2.4 | Inventory core | `stock_level`, `inventory_movement` (append-only + CHECKs), the single `apply_movements()` service with ordered locks, opening balances, stock adjustments with reasons, negative-stock policy (admin, audited) |
| 2.5 | Inventory UI and search | Inventory list with filters (low/out/active/category/supplier), movement history, adjustment form. Barcode lookup endpoint meets p95 < 100 ms with 50k products (load test). |
| 2.6 | Integrity verifier | Celery + beat. Nightly stock verifier with alerting. Concurrency test: N threads adjusting the same product never yield a wrong final quantity. |

## Phase 3 — POS

| # | Milestone | Acceptance criteria |
|---|---|---|
| 3.1 | Pricing module | Server pricing engine (line discount, order discount, tax-inclusive/exclusive, rounding) + `shared/pricing-test-vectors`. TS implementation passes the same vectors. |
| 3.2 | Payment methods | Configurable payment methods per org. Provider interface stub. |
| 3.3 | Complete sale API | Atomic sale with idempotency, `client_txn_id`, receipt numbering, price check (409), stock locks (422 with friendly message), mixed tenders, audit. **Concurrency test:** two cashiers race for the last unit and exactly one succeeds. **Fault-injection test:** a failure at each step leaves no partial rows. |
| 3.4 | POS screen (web) | Keyboard-wedge scanner detection, focused scan input, local product cache, quantity merge on rescan, keyboard shortcuts (F-keys for tenders), cart, tender dialog with change calculation, offline-tolerant error messages. Accessibility: fully keyboard-operable, screen-reader labels. E2E test with a simulated scanner. |
| 3.5 | Receipts | Receipt JSON/HTML (printable 58/80 mm CSS), reprint, delivery interface stub |
| 3.6 | Voids and returns | Void (same day, permissioned, reason) and returns with restock option, all via reversal movements |
| 3.7 | Cash sessions | Tills, open session with float, pay-in/pay-out/drop, blind close-out count, expected vs counted variance, X/Z reports, variance alerts, void allowed only while the session is open. Mobile: per-device till, synced as `cash_session.*` ops. |

**Demo:** open the till, scan products with a USB scanner, complete a mixed cash/mobile-money sale, print the receipt, see stock decrease and the movement history, void the sale, then close the till with a blind count and see the variance.

## Phase 4 — Customers and credit

| # | Milestone | Acceptance criteria |
|---|---|---|
| 4.1 | Customers | CRUD, search by name/phone, contact masking by permission, deactivate/pseudonymize |
| 4.2 | Accounts and ledger | `customer_account` + append-only ledger, credit limits, freeze, opening balances, ledger/statement endpoints, nightly ledger verifier |
| 4.3 | Credit sales | Credit and partial-credit tenders in the sale service, credit-limit enforcement and override permission, POS customer picker |
| 4.4 | Customer payments | Receive payment (partial, overpayment rule per Q-6), receipts, entry reversal. Concurrency test on simultaneous payments. |
| 4.5 | Reconciliation | Open/review/resolve workflow with snapshot, reason, permission, adjustment entry and audit; UI shows the transaction review |
| 4.6 | Debt aging | Aging buckets (0–30/31–60/61–90/90+), overdue flag, customer balances list |

## Phase 5 — Purchasing

| # | Milestone | Acceptance criteria |
|---|---|---|
| 5.1 | Direct receiving | Goods receipt without a PO: movements, weighted-average cost update, last purchase price, supplier ledger entry |
| 5.2 | Purchase orders | PO lifecycle, partial receiving against PO lines, over-receipt rule (Q-18) |
| 5.3 | Purchase returns | Returns to supplier with negative movements and supplier ledger credit |
| 5.4 | Supplier payables | Supplier payments, supplier statement, purchase history |

## Phase 6 — Android app

| # | Milestone | Acceptance criteria |
|---|---|---|
| 6.1 | App skeleton | Gradle modules (`app`, `core-domain` pure Kotlin, `core-data`, `feature-*`), Hilt DI, Compose design system, login with Keystore storage, device registration, CI build + unit tests |
| 6.2 | Local data | Room + SQLCipher. Pull sync of products, identifiers, stock, customers and payment methods, with a cursor. Repository tests. |
| 6.3 | Camera scanning | CameraX + ML Kit, format restrictions, debounce, haptic feedback, lookup against Room. Scanner workflow tests with recorded frames/fakes. |
| 6.4 | Mobile POS | Cart, pricing (passes shared vectors), tenders, credit sale, receipt view, offline indicator |
| 6.5 | Outbox and push sync | Outbox in the same Room transaction as the local sale. WorkManager sync with backoff, ordered ops, dependency handling, result mapping, conflict display. Server `/sync/push` and the conflict queue in web admin. **Tests:** duplicate push never creates duplicates; kill the app mid-sync and retry; clock skew. |
| 6.6 | Other mobile flows | Customer payments, customer lookup, stock adjustment (if permitted), goods receipt, quick-action dashboard |
| 6.7 | Device security | Revocation and quarantine, offline time limit, backup exclusion, release signing, Play internal track |

## Phase 7 — Reports and dashboard

| # | Milestone | Acceptance criteria |
|---|---|---|
| 7.1 | Dashboard | Sales today/week/month, transaction count, average basket, stock alerts, outstanding debt, recent purchases, sync failures, unusual adjustments |
| 7.2 | Sales reports | Daily/weekly/monthly, by product/category/cashier/payment method, store-timezone day boundaries |
| 7.3 | Inventory reports | Valuation (WAC), movements, low stock, adjustments, damaged/expired |
| 7.4 | Customer and supplier reports | Balances, aging, payments, purchases by supplier, price history |
| 7.5 | Exports | CSV/XLSX async exports via Celery, presigned downloads, rate-limited. Summary tables if query budgets are exceeded. |

## Phase 8 — Production hardening

| # | Milestone | Acceptance criteria |
|---|---|---|
| 8.1 | Database-level isolation | PostgreSQL RLS policies on all tenant tables, composite tenant FKs on financial tables, BOLA suite re-run with RLS on |
| 8.2 | Deployment pipeline | Staging auto-deploy, production promotion by image digest, migration job, health-gated rolling deploy, documented rollback. DEPLOYMENT.md. |
| 8.3 | Backups and DR | PITR enabled, encrypted backups, retention policy, **automated weekly restore test into staging**, RPO/RTO targets, DISASTER_RECOVERY.md runbook, game-day drill |
| 8.4 | Observability | Dashboards and alerts for SLOs, security events, Celery, sync, integrity drift. On-call runbook. |
| 8.5 | Performance | Load tests (k6) for lookup, sale and sync push at 10× expected peak. Query-count assertions. Index review. |
| 8.6 | Security assurance | ZAP scans, dependency and image scanning gates, audit hash chain (optional), step-up MFA, external penetration test with findings closed |
| 8.7 | Launch readiness | Privacy review (Kenya DPA if applicable), terms, data retention jobs, support tooling |

---

## Definition of Done (every milestone)
A feature is done when all of the following are true (spec §49):
- [ ] Backend service + API with serializers, validation and standardized errors
- [ ] Migrations, including DB constraints for invariants
- [ ] Authorization declared and covered by matrix + cross-tenant tests
- [ ] Audit events for sensitive actions
- [ ] Unit, API and (where relevant) concurrency and idempotency tests, all passing in CI
- [ ] Frontend (and mobile, where in scope) with loading, error and empty states, keyboard and screen-reader accessible
- [ ] OpenAPI schema updated; generated clients regenerated
- [ ] Logging/metrics considered; no sensitive data in logs
- [ ] Query performance checked (no N+1; indexes for new filters)
- [ ] Docs updated (API.md / DATABASE.md / ADR if a decision changed)
- [ ] Security self-review checklist in the PR template completed
