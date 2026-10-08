## What and why

<!-- What does this change do, and why? Link the roadmap milestone or issue. -->

## How it was tested

<!-- Commands run, new tests, manual checks. -->

## Definition of Done (docs/ROADMAP.md)

- [ ] Business rules enforced server-side (service layer), not only in the UI
- [ ] Migrations included; invariants protected by DB constraints where possible
- [ ] Every new endpoint declares its permission; cross-tenant access returns 404
- [ ] Financial/inventory writes are atomic and idempotent
- [ ] Sensitive actions write an audit record
- [ ] Tests cover success, validation, authorization and failure paths
- [ ] Loading, error and empty states; keyboard and screen-reader accessible (UI changes)
- [ ] API docs / OpenAPI schema updated
- [ ] Docs updated (API.md, DATABASE.md, an ADR if a decision changed)

## Security self-review

- [ ] No secrets, tokens or personal data in code, logs, fixtures or screenshots
- [ ] Input validated with explicit serializer fields (no mass assignment)
- [ ] Tenant/store scope comes from the session, never from client-supplied IDs
- [ ] No new raw SQL, `dangerouslySetInnerHTML`, or user-controlled URLs fetched server-side (or justified below)
