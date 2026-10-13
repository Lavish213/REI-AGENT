# Coordinated master issue log

This supplements the existing REI and Bob forensic ledgers. Each status applies to code repair, not deployment. The full overhaul remains incomplete.

| ID | Severity | Affected file/boundary | Root cause; fix | Verification/status |
|---|---|---|---|---|
| SYS-01 | Critical | Dashboard ingest.py, sophia_bridge.py | Empty secret permits anonymous mutations; use shared fail-closed constant-time verifier. | Recovered repair; isolated auth regressions required. |
| SYS-02 | High | Dashboard property_search.py | Provider failure fabricates owner, value and property; return genuine unavailable/error/empty. | Recovered repair; fault regressions required. |
| SYS-03 | High | Dashboard calls.py, dashboard/page.tsx | Call UUID used as Sophia UUID; resolve exact provider call metadata; deny ambiguous links. | Recovered repair; exact/ambiguous/absent mapping passes within 1,042-test hosted PostgreSQL/Redis suite. |
| SYS-04 | High | Sophia store, realtime stream hooks | Stale signals/context/dedup survive identity changes; reset by session, reject unrelated events. | Recovered repair; type/lint/build pass. |
| SYS-05 | High | Dashboard dashboard/page.tsx | Invented KPI trend arrays; remove fabricated history. | Recovered repair; type/lint/build pass. |
| SYS-06 | Medium | Six list pages and dashboard | Overlap, stale async responses, swallowed errors; existing TanStack Query cancellation and explicit failures. | Recovered repair; type/lint/build pass. |
| SYS-07 | High | Dashboard services/api.ts | Arbitrary absolute destinations get bearer token; reject non-service paths/redirects, bound request/refresh, release queue in finally. | Recovered repair; fault tests required. |
| SYS-08 | Critical | Dashboard package-lock.json | Baseline 1 critical and 4 high runtime advisories; graph upgraded to Next 16.4/ESLint 9 and patched dependencies. | Recovered runtime graph zero advisories; hosted frontend build/lint/type/fault/audit checks pass. |
| SYS-09 | Critical | Dashboard tests/conftest.py | Hardcoded personal database reset/Homebrew path; require explicit disposable test DSN and portable SQLAlchemy reset. | Recovered repair; four rejection cases pass; full suite requires disposable PostgreSQL. |
| SYS-10 | High | REI/dashboard ingestion boundary | Prefix mismatch, false acknowledgements, duplicate side effects and cross-database IDs. | Repaired canonical routes, versioned persisted receipts, explicit external/local lead mapping and replay/conflict guards. Verified in Dashboard SQL and REI receipt tests; durable outage outbox/order recovery remains open. |
| SYS-11 | High | Dashboard ingest.py / sophia_bridge.py | Latest lead session receives unrelated transcript; model classification can trigger follow-up without governance/idempotency. | Exact call sessions, persisted transcript chunks and dedup/conflict guards repaired. Dispositions are advisory pending approval; approved-action execution remains open. |
| SYS-12 | High | Dashboard migrations/models | Fresh install/provider enum/registration drift unverified. | Fresh empty-schema initialization verified: frozen 44-table/46-enum snapshot, rebuild/model comparison/idempotency and preserved historical single head. Legacy data upgrades and independent crash/concurrency remain open. |
| SYS-13 | High | Sophia agent.py | Model may omit AI disclosure or reveal property before identity; deterministic first utterance. | Recovered repair; unit rerun; actual phone opener not verified. |
| SYS-14 | High | Sophia runtime prompt | Claims recording, lead source or human callback without evidence. | Recovered prompt repair; generated speech evaluation remains open. |
| SYS-15 | High | Sophia tools.py / db.py | Past/naive appointments and unacknowledged writes claim success. | Partial: validation/ack repaired; availability reservation, cancellation/rescheduling/calendar delivery open. |
| SYS-16 | High | Sophia tools.py / context.py | Computed MAO becomes price authority. | Recovered repair: quoting unavailable until approved offer workflow exists; implement valid approval workflow before enabling. |
| SYS-17 | Critical | Sophia webhook.py / sms_webhook.py | Unsigned callbacks and caller-controlled stream lead identity. | Recovered signature/token repair; configure signing key/public HTTPS URL; replay and stream leases open. |
| SYS-18 | Critical | Sophia opt_out.py / migration 0011 | Prompt-only STOP does not persist suppression. | Recovered runtime interception/atomic phone-wide SQL; outage ends sales without false confirmation; durable recovery open. |
| SYS-19 | High | Sophia bob/checkbox_selector.py / worker.py | Attempts imply owner identity, cached address implies confirmation, vacancy implies spoken occupancy. | Open: attributable confirmed facts and versioned brief contract. |
| SYS-20 | High | Sophia Supabase/API membership | Broad authenticated RLS and insufficient operator scoping. | Open: explicit membership/least privilege and distinct-user enforcement tests. |
| SYS-21 | Medium | Sophia test configuration | setdefault can preserve live credentials; dummy loopback settings and deny unmocked DB clients. | Recovered repair; new tests use independent secure app; old unit route fixtures explicitly override auth. |
| SYS-22 | High | Shared REI/Bob baseline | Legacy tables absent from clean baseline. | Open: fresh schema and upgrade verification. |
| SYS-23 | Medium | React hooks/provider/CSS | Conditional hooks, ref reads, fabricated progress, nested component and invalid CSS import ordering. | Recovered repairs; current type/lint/build pass; screenshot QA open. |
| SYS-24 | Critical | REI context_tracker.py | STOP persistence receipt ignored; fixed success speech on failure. | Hosted CI 38281972038 passes 1,395 tests, 8 Bob/SQL contracts and 30 dashboard HTTP fault checks on recovered tree. |
| SYS-25 | High | Dashboard handoff/call mutation identity | Caller-selected operator attribution and read-only roles mutating calls. | Recovered role/identity/participant ownership repair; six independent handoff rejection cases pass. |
| SYS-26 | High | Full database harness | Embedded adapter loses transaction/error behavior; cannot count that run as green. | Resolved testing blocker: hosted CI 38282015032 passes 1,042 tests against disposable PostgreSQL/Redis. Production/migration gates remain open. |
| SYS-27 | Medium | Visual audit | Original managed-browser blocker resolved using authorized local Playwright and hosted CI. | Partial: design contract, 23-item dashboard issue log, 37 rendered states across 16 routes, 0 automated violations and 14 interactions; Dashboard CI 38328169737 green, including paginated/populated work, notification failure/retry, transcript races and account storage isolation. Populated production workflows and full cross-browser/a11y coverage remain open. See Dashboard docs/visual-audit/REPORT.md. |
| SYS-28 | High | Production voice/providers | Simulations do not prove accents/noise/muffled audio/duplex/hearing access, recovery, schedules, callbacks or durable volumes. | Open: approved real-call corpus, latency/turn metrics, provider outages and rollback drills. |
| SYS-29 | Medium | Dashboard properties/page.tsx | Storage failure still displayed save/remove success. | Second review repair: success toast requires storage acknowledgement; frontend checks required. |

## Additional confirmed findings

| ID | Severity | Affected file/boundary | Root cause; fix | Verification/status |
|---|---|---|---|---|
| SYS-30 | Critical | Production Compose/Docker/env | Environment mappings overrode production env files; inherited public service ports/mounts, localhost browser builds, missing backend startup/domain wiring. | Repaired explicit required production configuration, private service ports, removed source mounts, build-time/same-origin browser config, authenticated Redis health and startup. Hosted production merge check passed; real containers/TLS/backup remain open. |
| SYS-31 | High | WebsocketProvider / auth / realtime | Reusable JWT in query URL/logs; reconnection reused credentials. | Single-use Redis ticket <=20 seconds, atomic consumption, current active DB role, fresh reconnect and cancellation tests. Long-lived role/revocation policy after connect remains open. |
| SYS-32 | High | Dashboard scheduled work / leads API | First page looked complete; aggregates covered loaded records; date writes insufficiently bounded. | Server pagination/month filters, full-set deal totals, timezone/past-date validation, acknowledged cancellation; 201/203-record browser and SQL checks passed. |
| SYS-33 | High | Dashboard notifications/settings | Unscoped user IDs, absent server/team wiring and write-before-ack ambiguity. | Own/admin guards, readonly actual configuration/roster, commit-before-HTTP-ack/publication; SQL and populated role/fault checks passed. Internal durable notification outbox remains open. |

## Checklist

- [x] Architecture/inventory and ten-product desk research established before initial repairs.
- [x] Confirmed findings, root causes and required verification recorded.
- [x] Recovery commits preserve restored code; rerun verification proceeds against those files.
- [x] Recovered dashboard full backend suite and REI regression/contract checks pass hosted CI.
- [ ] Complete cross-project integration and migration gates green.
- [x] Screenshot-backed design contract and tested dashboard repairs published in Dashboard PR #1.
- [ ] Complete production-connected dashboard verification and manual multi-browser/accessibility coverage.
- [ ] Independent complete second audit against all original findings.
- [ ] Real phone and production infrastructure gates.

Nothing deployed, merged or connected to live callers. An overall A grade is not justified.


## Build configuration repair — 2026-10-13

SYS-34 (high): the dashboard instantiated its server Supabase client during module import. A clean production build without NEXT_PUBLIC_SUPABASE_URL/SUPABASE_SERVICE_KEY failed collecting /api/events with `supabaseUrl is required`; regression CI supplied dummy values and concealed the defect. Server pages/routes now obtain the client lazily at request time, and missing runtime configuration still fails without a fabricated database or acknowledgement. The shared client remains server-only. CI removes both values for the build, then uses isolated test values for HTTP fault checks.

Local verification: the previously failing no-credentials production build and TypeScript compilation now pass; dashboard lint passes. Hosted regression/Vercel verification follows the published source and must pass before merge. No deployment credentials were changed, and no database migration/provider action was performed.

## 2026-10-13 — durable phone suppression upgrade

Confirmed gap: inbound SMS STOP processing looked up and logged the lead before applying suppression. A datastore outage could lose the request. Direct SMS sends without a lead and the final phone adapter also lacked a universal phone-wide suppression guard.

Implemented: `CONTACT_SUPPRESSION_PATH` stores a permanent normalized phone block in a private SQLite WAL journal before datastore-dependent STOP work. Duplicate requests reuse one stable recovery identity. The recovery worker uses bounded backoff and generation-owned leases, requires matching remote suppression evidence and a readable DNC row, and reuses append-only evidence after acknowledgement loss. Local phone blocks remain after recovery. Call and SMS adapters deny suppressed numbers and fail closed on unavailable suppression checks. Enabling outbound operation now requires a usable persistent journal at startup. Existing journal file/directory/symlink checks apply. SMS unsubscribe confirmation requires acknowledged local or remote storage; unsupported START instructions were removed. Email templates no longer invent a nearby closing or describe Sophia as a human buyer.

Validation: 1,469 Python tests passed locally, including 17 new outage/restart/concurrency/receipt/startup cases. Actual PGlite migration checks also confirm service-role insertion/readback of suppression evidence and denial of evidence updates. Hosted CI and coordinated Bob/dashboard contracts are required before merge.

Deployment requirement: configure `CONTACT_SUPPRESSION_PATH` on a persistent private volume accessible to every process sharing this journal. Separate replicas without a shared journal still depend on recovered DNC state; this is not a distributed opt-out transaction. No journal rows are automatically released or expired. Protect and back up this sensitive volume. Email-address-wide suppression, explicit consent restoration, real provider/phone acceptance, external calendars and arbitrary legacy database operations remain separate gates. No live seller messages/calls or database migrations were performed in this pass. The overall production grade remains provisional; these tests do not establish an A or production uptime.
