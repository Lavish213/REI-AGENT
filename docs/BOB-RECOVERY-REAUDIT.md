# Bob–Sophia second audit and recovery upgrade

Target: **REI-AGENT repair branch + Bob-Intelligence repair branch**. The separate Sophia-Agent rebuild is incompatible: it owns its own Bob worker and uses seller_memory/lead_intel_packets instead of the REI schema. Do not run both planners against one project. Its original code was inspected for comparison, not repaired or deployed in this campaign.

## Implemented boundaries

- Shared V2 advisory brief remains the actual Bob → Sophia connection. No brief, event or mood grants dialing, pricing or tool authority.
- Removed the unused embedded REI Bob planner and unversioned contract. Owner check-in calls carry no seller brief.
- Facts now enter a SQLite WAL journal during the live pipeline. Disk/network writes run outside speech frame handling. Successful appointment/callback tools journal next-step evidence immediately. Hangup makes another journaling attempt.
- Local journal uses stable payload-bound event IDs, tenant filtering, generation-owned delivery leases, bounded exponential retry and acknowledged deletion. Supabase atomically merges facts and writes a bound receipt. Replay cannot overwrite newer evidence; denial wins equal timestamps; unchanged old facts do not trigger replanning.
- Unrelated speech no longer refreshes old ownership/motivation evidence. Questions and hypothetical statements do not become positive checklist facts. A wrong spoken address cannot replace the canonical property address. These deterministic rules remain conservative heuristics, not human transcript adjudication.
- Expired undelivered facts become visible dead letters rather than entering a fresh brief. Corrupt historical timestamps no longer poison valid new evidence.
- Bob mood must have fresh seller provenance. Free-form strategy strings cannot be copied into model instructions; approved strategy codes map to fixed guidance.
- Added an authenticated REI receiver at `/api/ingest/bob/brief-created`. It only acknowledges an exact event already committed in the shared Bob outbox; it durably records receipt and triggers no call/tool action. Sender requires the matching `{status: persisted, event_id}` response, not any HTTP 200.
- Bob requires an explicit **full** `BOB_EVENT_URL`. Karpathys source inspection found `/api/v1/ingest` and no Bob route, so the old guessed route was removed. This adapter targets REI, not Karpathys.
- Bob startup verifies shared contract 2.1 and fails on an incompatible/missing schema. Worker heartbeats, quarantine/dead-event counts, queue age and stale-brief counts are available through service-only RPCs and operator-protected `/api/bob/health`. Missing/old/error heartbeats report degraded.
- Removed duplicate context accessor and duplicate Karpathys event functions.

## Deployment contract

1. Keep outbound disabled. Both services must use the same Supabase project and tenant. REI `TENANT_ID` must equal Bob `BOB_TENANT_ID`.
2. Apply Bob migrations `20261011_bob_durable_briefs.sql`, then `20261013_bob_feedback_health.sql`, exactly once after the confirmed REI baseline. This does not reconstruct the missing full baseline.
3. Mount a **persistent writable volume** in the REI deployment. Set `VOICE_FACT_OUTBOX_PATH=/data/sophia/bob-facts.sqlite3`. One recovery worker must share that exact volume and environment. An ephemeral container disk cannot provide restart durability across replacement.
4. Setting `VOICE_FACT_OUTBOX_PATH` starts a recovery task every 30 seconds independently of campaign/background calling. Alternatively run `python -m backend.voice.bob_recovery` as another process on the **same host and local volume**. SQLite WAL is not supported over a network filesystem; do not share it between hosts.
5. Optional brief notifications: set Bob `BOB_EVENT_URL=https://<rei-backend>/api/ingest/bob/brief-created`, and set the same nonempty `KARPATHYS_WEBHOOK_SECRET` on both services. Leave URL empty to disable notifications. Shared brief consumption works without events.
6. Bob `python -m backend.main --health`; REI `python -m backend.voice.bob_recovery --health`; operator `/api/bob/health`. Configure an actual monitor to alert on degraded/503. The code cannot configure an inaccessible production monitor.
7. Exercise database outage, worker kill/restart, two independent PostgreSQL workers, receipt retries and restored volume in staging. Then make consented calls to operator-controlled numbers and review audio/transcripts/provider outcomes.

Journal limit: 10,000 retained rows, no silent eviction. Exhaustion is an error. Inspect/deal with dead letters and archive deliberately. Fact freshness remains 24 hours; prolonged outage can expire evidence. Delivered local rows are deleted; shared receipts/decisions require an operator-defined retention plan. The journal stores checklist evidence and identifiers, not transcripts or phone audio. Restrict volume access and backups.

## Evidence and grade limits

The new round-trip harness executes the actual Bob Python generator, actual Sophia brief loader/context tracker, and both migrations in PGlite. It verifies identity → six discovery facts → next-step planning, denial replay, uncertain speech and suppression. It uses synthetic text and embedded PostgreSQL; it does not prove live ASR, independent backend concurrency, or production deployment.

The engineering grade can improve after these repairs, but **the system is not certified A**. Missing full schema baseline, production volume/monitor setup, real phone/audio acceptance, actual provider recovery and remaining scheduling/approval workflows remain release gates. Market enrichment and autonomous underwriting were never implemented in Bob; adding fictional data or an unapproved offer engine would not close that gap.

Nothing merged, deployed, migrated on a live project, called, texted or emailed.

## Final local verification

- Bob: **237 passed**, 87.9% statement / 70.3% branch / 83.6% combined coverage. These figures expose remaining untested behavior; they are not an A grade.
- Shared migrations: **51 checks passed**, including tenant boundaries, exact receipt binding, tie-denial precedence, corrupt legacy data, source-stability and rollback.
- Cross-repository executable round trip: **eight checks passed** through actual producer, consumer and SQL.
- REI full suite: **1,395 passed**, four dependency deprecation warnings. The 41 new recovery tests include 32 concurrent real SQLite submissions, outage retention, tenant isolation, hard process exit after commit, crash during delivery with lease/replay, capacity exhaustion, receipt authentication, degraded health, false affirmatives and recovery while campaign jobs are disabled.
- Critical/unused-import/duplicate-definition static checks, compilation and whitespace checks passed. Hosted CI must run again on the final published trees; prior green runs predate these changes.

Second pass re-read the repaired Bob source and re-traced both directions, authentication, acknowledgment, job/source leases, file persistence, timestamp precedence, authority boundaries and shutdown. It found and repaired the guessed Karpathys route, SQLite deployment constraints, observation refresh, free-form guidance and duplicate functions. This is a bounded code audit, not proof that no unknown bugs exist.

Hosted Bob CI run 38173657503 and coordinated REI run 38173684445 passed, including the actual cross-repository round trip. Final log review also found dashboard dependency vulnerabilities; the subsequent security upgrade and remaining development-only advisory are recorded in [DASHBOARD-DEPENDENCY-SECURITY.md](DASHBOARD-DEPENDENCY-SECURITY.md). That follow-up receives its own hosted regression run. Bob ledger remains 51 findings; the separate REI ledger now contains 183 entries.

Implementation references: PostgreSQL [queue locking](https://www.postgresql.org/docs/17/sql-select.html) and SQLite [WAL durability and same-host restriction](https://www.sqlite.org/wal.html). Do not mount the journal on a network filesystem.
