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
make help    # all commands
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and the development workflow.

## Status

**Phase 1 (foundation) in progress.** Milestones 1.1–1.7 are done: repo skeleton, local environment, CI, Django core, authentication, and multi-business tenancy (sign-up, stores, staff, roles and permissions, audit log). Milestone 1.7 (idempotency, least-privilege database roles) is done too. Next: the web shell (1.8).

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
