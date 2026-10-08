# Contributing to ShopFlow

## Workflow
1. Branch from `main`: `feat/<milestone>-<short-name>` or `fix/<short-name>`.
2. Keep pull requests small and vertical: one milestone slice per PR (see [docs/ROADMAP.md](docs/ROADMAP.md)).
3. CI must pass and one review must approve before merging. Nobody pushes directly to `main` once branch protection is enabled.
4. Fill in the PR template, including the Definition of Done and the security self-review.

## Local setup
Requirements: Docker (with Compose v2) and `make`. Node 24 and Python 3.13 are only needed if you run tools outside Docker.

```bash
cp .env.example .env      # optional; defaults work for local development
make up                   # build and start db, redis, backend, frontend
make test                 # backend + frontend tests
make lint                 # ruff, mypy, migration check, eslint, tsc
```

- Web app: http://localhost:3000 (proxies `/api/*` to Django)
- API docs (development only): http://localhost:8000/api/v1/docs/
- Readiness probe: http://localhost:8000/readyz

Install the git hooks once (needs [pre-commit](https://pre-commit.com)):

```bash
pipx install pre-commit   # or: brew install pre-commit
pre-commit install
```

## Backend conventions
- **Business logic lives in `services.py`.** Views validate, authorize and call a service. Each service function is one `transaction.atomic()` unit.
- Reads go in `selectors.py`, and every query is scoped to the caller's organization (from Phase 1.6).
- Money uses `MoneyField`, quantities use `QuantityField` (`apps/common/fields.py`). Never use floats.
- Raise `ApplicationError` subclasses with a stable `code` for business-rule failures. Their `detail` must be readable by a shopkeeper.
- Every model change ships with its migration. CI fails on missing migrations.
- Dependencies: edit `backend/pyproject.toml`, then refresh the lockfile with `docker compose run --rm backend uv lock`.

## Frontend conventions
- After changing an API endpoint, run `make api`: it regenerates `shared/openapi.yaml` and `frontend/src/lib/api/schema.d.ts`. CI fails if either is stale.
- Call the API only through `api` in `src/lib/api/client.ts` (typed, with CSRF and session refresh), and wrap calls in `unwrap()` so failures become `ApiError`s with the server's message.
- Creates of business records send an `Idempotency-Key` (`newIdempotencyKey()`), one per form, so double-submits are harmless.
- Server state lives in TanStack Query; avoid global client stores.
- New screens get an end-to-end test with an axe audit (`e2e/helpers.ts: expectAccessible`).
- No inline `style={...}` attributes: the production CSP blocks them. Use Tailwind classes.
- TypeScript strict mode. No `any` without a comment explaining why.
- Components handle loading, error and empty states, and are keyboard and screen-reader accessible.
- No tokens in `localStorage`/`sessionStorage`. Authentication uses HttpOnly cookies (docs/SECURITY.md §2).

## Security
- Never commit secrets. `.env` is git-ignored; use `.env.example` for placeholders. Gitleaks runs in pre-commit and CI. If a real value trips it, rotate the secret before doing anything else.
- New `.gitleaks.toml` exceptions must name the exact value and explain why it isn't a secret.
- CI blocks merges on high/critical vulnerabilities in runtime dependencies and container images. Dev-only tooling advisories with no available fix are tracked through Dependabot rather than blocking CI.
- Report vulnerabilities privately to the maintainers, not in public issues.

## Commit messages
Use [Conventional Commits](https://www.conventionalcommits.org): `feat(sales): …`, `fix(inventory): …`, `docs: …`, `chore(ci): …`.
