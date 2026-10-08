# ShopFlow

Point of Sale, inventory, customer credit, supplier and reconciliation management for small and medium retail businesses.

- **Web:** Next.js + TypeScript, for POS and back office, with USB/Bluetooth barcode scanners
- **Mobile:** Android (Kotlin, Jetpack Compose), with camera barcode/QR scanning and offline sales with safe sync
- **Backend:** Django + Django REST Framework + PostgreSQL, with Redis/Celery for background work

## Status

**Phase 0: design.** No application code yet. The design documents are ready for review:

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, module layout, request lifecycle, architecture decision records, key flows (sale, sync, scanning) |
| [docs/DATABASE.md](docs/DATABASE.md) | ERD, constraints, indexes, append-only tables, invariant enforcement |
| [docs/API.md](docs/API.md) | API conventions, error format, idempotency, endpoint inventory with examples |
| [docs/SECURITY.md](docs/SECURITY.md) | Authentication, tokens, RBAC, tenant isolation, OWASP controls, audit, secrets, privacy |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phased milestones with acceptance criteria and Definition of Done |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decisions on ambiguous requirements (all accepted) |

`DEPLOYMENT.md`, `CONTRIBUTING.md` and `DISASTER_RECOVERY.md` are written in the phases that produce what they describe (see the roadmap). Local setup instructions arrive with Phase 1.
