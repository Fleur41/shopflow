# ShopFlow Android app

Placeholder. The Android app (Kotlin, Jetpack Compose, CameraX + ML Kit scanning, Room with SQLCipher, WorkManager sync) is built in **Phase 6** of [docs/ROADMAP.md](../docs/ROADMAP.md).

The backend contract it depends on (`client_txn_id`, `occurred_at`, idempotency keys, `/sync/push` and `/sync/pull`) is specified in [docs/API.md](../docs/API.md) §3 and §4.13, and is built into the sales and payments endpoints from Phase 3 onwards.
