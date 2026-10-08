# ShopFlow

Point of Sale, inventory, customer credit, supplier and reconciliation management for small and medium retail businesses.

- **Web:** Next.js + TypeScript, for POS and back office, with USB/Bluetooth barcode scanners
- **Mobile:** Android (Kotlin, Jetpack Compose), with camera barcode/QR scanning and offline sales with safe sync
- **Backend:** Django + Django REST Framework + PostgreSQL, with Redis/Celery for background work

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | Django + DRF API (Python 3.13, PostgreSQL 17, Redis) |
| `frontend/` | Next.js web app (TypeScript strict, Tailwind) |
| `mobile/` | Android app (Phase 6, placeholder) |
| `docs/` | Architecture, database, API, security, roadmap, decisions |
| `compose.yaml`, `Makefile` | Local development environment |
| `.github/` | CI, Dependabot, PR template |

## Quick start

Requires Docker and `make`.

```bash
make up      # http://localhost:3000 (web), http://localhost:8000/api/v1/docs/ (API docs)
make test    # backend + frontend tests
make lint    # linters and type checks
make e2e     # browser end-to-end + accessibility tests (needs `make up`)
make api     # regenerate the OpenAPI schema and TypeScript API types
make help    # all commands
```

Open http://localhost:3000 and choose **Register your business** to get started. Emails sent locally (verification, password reset, invitations) appear in Mailpit at http://localhost:8025.

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and the development workflow.

## Status

**Phase 1 (foundation) is complete.** It covers authentication with two-step verification, multi-business tenancy (stores, staff, roles, invitations, audit log), duplicate-request protection, least-privilege database roles, email flows, and the web app shell. Next: **Phase 2, products, barcodes and inventory.**

## Design documents

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, module layout, request lifecycle, architecture decision records, key flows (sale, sync, scanning) |
| [docs/DATABASE.md](docs/DATABASE.md) | ERD, constraints, indexes, append-only tables, invariant enforcement |
| [docs/API.md](docs/API.md) | API conventions, error format, idempotency, endpoint inventory with examples |
| [docs/SECURITY.md](docs/SECURITY.md) | Authentication, tokens, RBAC, tenant isolation, OWASP controls, audit, secrets, privacy |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phased milestones with acceptance criteria and Definition of Done |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decisions on ambiguous requirements (all accepted) |

`DEPLOYMENT.md` and `DISASTER_RECOVERY.md` are written in Phase 8, when there is a deployment to describe.
