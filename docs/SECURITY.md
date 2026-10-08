# ShopFlow — Security Model

Status: **Draft for review** (Phase 0). Covers authentication, authorization, token handling, tenant isolation, API security, audit logging, secrets, logging and privacy.

To report a vulnerability, email the maintainers privately (address TBD). Do not open a public issue.

---

## 1. Threat model summary

| Asset | Main threats | Primary controls |
|---|---|---|
| Financial records (sales, payments, ledgers) | Tampering, deletion, fraud by insiders, duplicate submission | Append-only tables, DB grants, audit log, idempotency, permissions on voids/adjustments |
| Inventory | Silent adjustment hiding theft | Movement-only changes, reasons required, audit, unusual-adjustment alerts |
| Tenant data | Cross-tenant access (IDOR/BOLA) | Scoped querysets, 404 on foreign IDs, cross-tenant test suite, RLS (Phase 8) |
| Customer personal data | Leakage, over-collection | Data minimization, contact masking by permission, log redaction, encrypted backups |
| Accounts | Credential stuffing, session theft, privilege escalation | Argon2id, rate limits and lockout, MFA for privileged roles, HttpOnly cookies, refresh rotation with reuse detection, role-grant restrictions |
| Mobile devices | Lost or stolen phone holding tokens and cached data | Keystore-protected tokens, SQLCipher-encrypted Room DB, device revocation, offline time limit |

Attackers considered: an external unauthenticated attacker; an authenticated user of another organization; a low-privilege insider (cashier); a thief holding a lost device.

---

## 2. Authentication

### 2.1 Credentials
- Passwords are hashed with **Argon2id** (Django `Argon2PasswordHasher` first in `PASSWORD_HASHERS`; older hashes upgrade on login).
- Django password validators require at least 10 characters, block common and breached passwords, and reject passwords similar to user attributes.
- Plaintext passwords are never logged or stored. Serializers mark them `write_only`, and the log redactor drops `password*` keys.

### 2.2 Tokens and sessions

| Token | Form | Lifetime | Storage (web) | Storage (Android) |
|---|---|---|---|---|
| Access | JWT (HS256, `kid` header for key rotation; `iss`/`aud`/`typ` verified). Claims: `sub`, `sid`, `iat`, `exp`, `jti`. **No permissions or personal data in the token.** | 10 min | `__Host-sf_at` cookie: HttpOnly, Secure, SameSite=Lax, Path=/ | Memory, plus Keystore-wrapped encrypted storage |
| Refresh | 256-bit opaque random value; the server stores only its SHA-256 hash (`accounts_refreshtoken`) | 14 days idle / 30 days absolute (web); 30 days idle / 90 days absolute (mobile) | `__Secure-sf_rt` cookie: HttpOnly, Secure, SameSite=Strict, Path=`/api/v1/auth/` | Keystore-wrapped encrypted storage |

- **Rotation:** every refresh issues a new refresh token and invalidates the old one.
- **Reuse detection:** presenting an already-rotated refresh token more than 20 seconds after its rotation revokes the **whole session** (every token in the chain) and logs `auth.refresh_token_reuse_detected`. That pattern means the token was copied. Within 20 seconds it is treated as a benign race, such as two browser tabs refreshing together: the response is `409 REFRESH_IN_PROGRESS` and nothing is revoked. Refreshes of one token are serialized with a row lock, so concurrent refreshes yield exactly one new token (covered by a threaded test). Emailing the user about reuse arrives with email delivery in 1.9.
- **Revocation:** every request checks the token's session (`sid`), cached for at most 30 s. Revoking a session deletes its cache entry immediately and again after commit, so logout, logout-all and session revocation take effect **on the next request**. The cache TTL only bounds staleness if a cache delete is lost. Deactivated users are rejected on the next request too.
- **Permissions** are resolved per request from the membership (cached and invalidated on change). Role changes apply right away without reissuing tokens.
- **Business-scoped sessions:** a session belongs to one business, recorded on the session row (deliberately not as a token claim, so it can't go stale). Switching business creates a new session after verifying membership and ends the old one. Clients never send a business ID on ordinary requests.

### 2.3 Web: CSRF and CORS
- The web app and API share one origin (`/api/*` is proxied), so cookies are first-party and **CORS is disabled** for the web app.
- Cookie-authenticated unsafe requests (POST/PUT/PATCH/DELETE) must pass Django CSRF checks (the `X-CSRFToken` header must match the `csrftoken` cookie). `SameSite` is defence in depth, not the only control.
- Login and refresh with `client: "web"` are CSRF-checked too: they set cookies, so login CSRF must be prevented. Clients get the token from `GET /auth/csrf/`. CSRF failures return `403 CSRF_FAILED` as JSON.
- Bearer-authenticated requests (mobile) are not CSRF-checked, because browsers never attach such headers automatically.
- `CORS_ALLOWED_ORIGINS` stays empty unless a separate origin is ever needed. In that case it gets an explicit allowlist and never `*` with credentials.

### 2.4 MFA
- TOTP (RFC 6238) with 10 single-use recovery codes, stored hashed. The TOTP secret is encrypted at rest with a key from the secrets manager.
- **Required** for any membership whose role includes a permission marked `is_sensitive` (Owner/Admin by default). Optional for others.
- Step-up: sensitive operations (role changes, negative-stock policy, reconciliation over a threshold) can require a fresh MFA check within the last 15 minutes (Phase 8).

### 2.5 Account lifecycle
- **Email verification:** single-use token (stored hashed), 24 h expiry.
- **Password reset:** single-use token (stored hashed), 30 min expiry. The response is always `202` (no enumeration). A successful reset revokes all sessions.
- **Brute force:**
  - per-email (5/min) and per-IP (20/min) throttles (§6);
  - temporary lock after 10 failures in 15 min, lasting 15 min. The lock is per email address and applies to unknown addresses too, so lockout never reveals whether an account exists;
  - wrong password, unknown email and inactive account all return the identical `401 INVALID_CREDENTIALS`, and Django runs the password hasher for unknown users to equalise timing;
  - every failed attempt is logged as `auth.login_failed` with a hashed email fingerprint, never the email or password. Email notification of a lock arrives in 1.9.

### 2.6 Mobile device binding
- On first login the device registers (`sync_device`) and the session is bound to it.
- An admin can revoke a device. The next request gets `401 DEVICE_REVOKED`. The app stops selling, and any unsynced outbox ops are uploaded to a **quarantine** for review, not applied and not deleted. Then local data is wiped.
- **Offline limit:** the app works offline for at most `OFFLINE_MAX_HOURS` (default 72) since the last successful refresh.
- **Local data:** the Room database is encrypted with SQLCipher, using a key in Android Keystore. App backups are excluded (`android:allowBackup="false"` and data extraction rules). Root/emulator detection is advisory only.

---

## 3. Authorization

### 3.1 Model

```text
User ─< Membership >─ Organization
           │  role ──< RolePermission >── Permission (code catalog)
           └─ stores: all_stores=true, or explicit MembershipStore rows
```

The effective permission for request R on store S is:
`membership(user, session.org).status == ACTIVE` **and** `S ∈ membership.stores` **and** `perm ∈ role.permissions`.

### 3.2 Permission catalog (initial)

| Area | Codes |
|---|---|
| Organization | `org.view`, `org.manage`*, `stores.view`, `stores.manage`*, `stores.manage_inventory_policy`* |
| Users / roles | `users.view`, `users.manage`*, `roles.view`, `roles.manage`* |
| Catalog | `products.view`, `products.manage`, `products.change_price`* |
| Inventory | `inventory.view`, `inventory.view_movements`, `inventory.manage_levels`, `inventory.adjust`*, `inventory.receive` |
| Sales | `sales.create`, `sales.view_own`, `sales.view_all`, `sales.discount`, `sales.override_price`*, `sales.credit`, `sales.void`*, `sales.return`* |
| Customers | `customers.view`, `customers.view_contact`, `customers.create`, `customers.manage`, `customers.view_balance`, `customers.receive_payment`, `customers.set_credit_limit`*, `customers.exceed_credit_limit`*, `customers.reverse_entry`*, `customers.reconcile`* |
| Suppliers / purchasing | `suppliers.view`, `suppliers.manage`, `purchasing.view`, `purchasing.create_po`, `purchasing.receive`, `purchasing.return`, `purchasing.view_payables`, `purchasing.pay_supplier`* |
| Cash control | `cash.open_session`, `cash.close_session`, `cash.pay_in_out`, `cash.view_sessions`, `cash.correct`* |
| Reports / audit | `reports.view`, `reports.view_customers`, `reports.view_all_stores`, `audit.view`* |
| Sync | `sync.register_device`, `sync.resolve_conflicts`* |

`*` = `is_sensitive`: requires MFA for holders, and every use is audited.

Value limits that sit alongside permissions are stored as role attributes, e.g. `max_discount_percent` (cashier default 0 %) and `max_adjustment_value`.

### 3.3 Default role templates
These are copied into each new organization as editable roles. Owner is not editable, and the last Owner cannot be removed.

| Permission group | Owner | Manager | Cashier |
|---|---|---|---|
| Org, users, roles, policies | ✅ | view only | — |
| Products / prices | ✅ | ✅ | view |
| Inventory adjust | ✅ | ✅ | — (configurable) |
| Receive stock | ✅ | ✅ | ✅ (configurable) |
| Sell, credit sale, receive customer payment | ✅ | ✅ | ✅ |
| Discounts / price override | ✅ | ✅ (limit) | — |
| Void / return | ✅ | ✅ | — |
| Open/close own till, pay-in/out | ✅ | ✅ | ✅ |
| View all sessions / variances, corrections | ✅ | ✅ (view) | — |
| Credit limits, reversals, reconciliation | ✅ | — (configurable) | — |
| Reports | ✅ | ✅ | own sales only |
| Audit log | ✅ | — | — |

Manager is an addition to the two roles in the spec. It is a common need and costs nothing, because roles are data.

Managers have **view-only** access to staff and roles by default; only Owners (or custom roles granted `users.manage` / `roles.manage`) manage staff.

### 3.4 Enforcement layers
1. **Route declaration.** Every business-scoped view extends `TenantAPIView` and declares `required_permissions` per HTTP method; an undeclared method is denied. `tests/test_authorization_coverage.py` walks every API route and **fails the build** unless each is a tenant view with valid declarations or is on an explicit public / account-scoped allowlist.
2. **Tenant-scoped data access.** `Model.objects` on tenant models raises `UnscopedQueryError` unless scoped with `.for_org(...)`; Django internals use a separate `unscoped` default manager. IDs in request bodies resolve through scoped querysets, so another business's ID fails like a nonexistent one. Every ID in the path or body is resolved through `for_org(ctx)`, and `for_store(ctx, store)` where relevant.
3. **Service-level rules.** Value-based checks (discount limits, credit limit overrides, return quantities) run inside the transaction.
4. **Database.** Row-Level Security policies keyed on a per-transaction `app.current_org` setting (Phase 8), plus constraints.

### 3.5 Privilege escalation guards
- A user can grant or assign only roles whose permission set is a **subset** of their own. Only Owners can make Owners.
- A user can manage only members (and edit only roles) whose permissions are a subset of their own.
- Store access you grant must be within your own; store-limited users cannot grant all-stores access.
- Users cannot change their own role, store access or status.
- The last active Owner cannot be suspended or demoted. Owner rows are locked during the check, so two owners cannot remove each other concurrently.
- Role and member changes are audited with old and new values. MFA for these sensitive permissions arrives in 1.9.

---

## 4. Tenant isolation

- The organization comes **only** from the authenticated session. Store IDs come from the URL and are checked against membership. Org/store fields in request bodies are ignored or rejected. Serializers mark `organization`, `store`, `created_by`, `cashier` etc. as read-only (this also prevents mass assignment).
- Cross-tenant references are rejected. For example, a sale line pointing at another org's product returns `422`/`404`, because lookup goes through the scoped queryset.
- **Automated BOLA suite** (`tests/test_cross_tenant_access.py`): every route with a path ID is called by business B's owner (who holds every permission in B) with business A's IDs, for every method, with a body that passes validation. Each call must return 404 and A's data must be unchanged. List endpoints must never include A's IDs. New routes with IDs fail the suite until registered. Store-level scoping within one business is covered by the tenancy tests.
- Caches are keyed by `org_id` (and `store_id`), never by bare object ID.
- Object storage keys are prefixed `org/{org_id}/…`, and access goes only through short-lived presigned URLs issued after an authorization check.
- Phase 8 adds PostgreSQL RLS and composite `(organization_id, id)` FKs on financial tables, so the database itself refuses cross-tenant reads and writes.

---

## 5. OWASP coverage

| Risk | Control |
|---|---|
| SQL injection | ORM / parameterized queries only. Raw SQL is allowed only in reviewed `selectors` with params. Bandit + Semgrep rules in CI. |
| XSS | React escaping. `dangerouslySetInnerHTML` banned by lint. Strict CSP with nonces (`default-src 'self'`, no `unsafe-inline` scripts). Receipt HTML rendered with Django autoescape. |
| CSRF | §2.3 |
| SSRF | The server never fetches user-supplied URLs. Outbound integrations use allowlisted hosts. Image import is upload-only, never URL fetch. |
| IDOR / BOLA | §3.4, §4 |
| Broken authentication | §2 |
| Privilege escalation | §3.5 |
| Mass assignment | Explicit serializer field lists. `read_only_fields` for tenant, audit and ownership fields. No `fields = "__all__"` (lint check). |
| Insecure uploads | §7 |
| Brute force / API abuse | §6 |
| Replay | Idempotency keys + `client_txn_id` uniqueness. Short-lived access tokens. Refresh rotation. Single-use reset/verify tokens. |
| Security misconfiguration | `DEBUG=False` enforced in prod settings (startup assertion). `manage.py check --deploy` in CI. Admin site behind an IP allowlist + MFA, on a non-default path. |
| Vulnerable dependencies | §9 |

### Security headers (proxy + Django)
- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
- `Content-Security-Policy` (nonce-based)
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`. Camera becomes `(self)` only if browser camera scanning is added later.
- `X-Frame-Options: DENY` / `frame-ancestors 'none'`
- Cookies: `Secure`, `HttpOnly` (except `csrftoken`), and `SameSite`.

---

## 6. API protection

| Scope | Limit (initial, tunable) |
|---|---|
| `POST /auth/login/` | 5/min per email, 20/min per IP |
| `POST /auth/refresh/` | 60/min per IP |
| `POST /auth/password/reset/` | 3/hour per email, 10/hour per IP |
| `POST /auth/mfa/verify/` | 5 per `mfa_token` |
| Authenticated API, general | 600/min per user (anonymous: 120/min per IP) |
| `GET …/products/lookup/` | 1200/min per user (scanners are fast) |
| `/sync/push/` | 60/min per device, max 50 ops / 1 MB per batch |
| Report exports | 10/hour per user |

Limits are implemented with DRF throttles backed by Redis, plus coarse per-IP limits at the proxy. Request bodies are capped at 1 MB (10 MB on upload endpoints). Page size is capped at 200.

---

## 7. File uploads (product images)
- Allowed types: JPEG, PNG, WebP. The type is checked by **decoding** with Pillow, not by trusting the extension or Content-Type. Max 5 MB, max 4096×4096.
- Images are re-encoded server-side, which strips metadata and EXIF GPS data and neutralizes polyglot files. They are stored under random keys, never under user-supplied filenames.
- Images are served from object storage or a CDN on a separate origin, with `Content-Disposition: inline`, the correct `Content-Type`, and `nosniff`. Nothing uploaded is ever executed or served from the app origin.

---

## 8. Logging, monitoring and privacy in telemetry

- **Structured JSON logs** with `request_id`, `org_id`, `store_id`, `user_id`, `device_id`, route, status and latency.
- **Never logged:** passwords, tokens (access, refresh, reset, MFA), `Authorization`/`Cookie` headers, TOTP secrets, full card data (we never receive it), or full request bodies on auth and payment routes. A redaction processor removes keys matching `password|token|secret|authorization|cookie|otp|pin` and masks phone numbers and emails (`+2547••••123`).
- **Sentry:** `send_default_pii=False`, a `before_send` scrubber, and request bodies off.
- **Security events** go to a dedicated logger and raise alerts:
  - failed logins above a threshold;
  - refresh token reuse;
  - MFA disable;
  - role/permission changes;
  - negative-stock policy changes;
  - adjustments above a value threshold;
  - voids above N per cashier per day;
  - cash-session variances above the store threshold;
  - sync conflicts;
  - integrity-verifier drift.

---

## 9. Secrets and supply chain

- Secrets come from environment variables injected by the platform's secrets manager. **Never from committed files.**
- `.env` is git-ignored. `.env.example` holds placeholders only.
- **gitleaks** runs in pre-commit and CI.
- Each environment has separate credentials. Production credentials are never used locally.
- JWT signing keys carry a `kid` for rotation (old keys stay valid for verification during the rotation window). The DB password, `SECRET_KEY` and the TOTP encryption key are rotated on a schedule and on any suspected exposure.
- Separate DB roles: `shopflow_migrator` (DDL, CI/CD only) and `shopflow_app` (DML, with no UPDATE/DELETE on append-only tables).
- **Scanning in CI:** `pip-audit`, `npm audit`/`osv-scanner`, Gradle dependency check, Trivy for container images, Bandit + Semgrep for SAST, CodeQL, and Dependabot or Renovate for updates. High/critical findings block merges.
- Container images: pinned base digests, a non-root user, a read-only root filesystem where possible, no build tools in runtime images.

---

## 10. Audit logging

- **Written in the same DB transaction** as the change it describes, so an audited action can't commit without its audit row.
- **Fields:**
  - `actor` (user/system/device), `organization`, `store`;
  - `action` (e.g. `product.price_changed`, `inventory.adjusted`, `sale.voided`, `customer.ledger_reversed`, `reconciliation.resolved`, `membership.role_changed`);
  - `entity_type`/`entity_id`;
  - `changes` (`{field: [old, new]}`, with personal data minimized);
  - `reason`, `request_id`, `ip`, `user_agent`, `device_id`, `occurred_at`.
- **Immutability:** a DB trigger (`shopflow_prevent_modification`) rejects UPDATE and DELETE from any code path, including raw SQL. Separate DB roles (no UPDATE/DELETE grants for the app role) follow in 1.7. No API endpoint can modify or delete audit rows, not even for Owners. Phase 8 option: a hash chain (`prev_hash`) for tamper evidence, with periodic export to WORM storage.
- **Retention:** default 7 years, configurable, subject to confirmation of local tax-law requirements (DECISIONS Q-19).

---

## 11. Data protection and privacy

- **Minimization:** a customer needs only a name. Phone, email and address are optional. No national ID numbers are collected.
- Contact fields are visible only with `customers.view_contact`, and masked otherwise.
- **Data subject requests:**
  - export of a customer's data;
  - erasure by **pseudonymizing** the customer record (name → "Deleted customer #…", contact fields cleared) while keeping financial entries, which must be retained for legal and accounting reasons.
- If operating in Kenya, the **Data Protection Act 2019** applies, including ODPC registration where required. Legal review is needed before launch; this is not legal advice.
- **Encryption:** TLS 1.2+ in transit. Encrypted storage and encrypted backups at rest (provider-managed keys at minimum). TOTP secrets are additionally encrypted at the application level.

---

## 12. Security testing
- Authorization matrix tests (role × endpoint), cross-tenant BOLA suite, CSRF tests, token rotation and reuse tests.
- OWASP ZAP baseline scan against staging in CI (nightly).
- Pre-launch: an external penetration test (Phase 8). Findings are tracked to closure.
