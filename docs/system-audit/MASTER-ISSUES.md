# Coordinated master issue log

This supplements the existing REI and Bob forensic ledgers. Each status applies to code repair, not deployment. The full overhaul remains incomplete.

| ID | Severity | Affected file/boundary | Root cause; fix | Verification/status |
|---|---|---|---|---|
| SYS-01 | Critical | Dashboard ingest.py, sophia_bridge.py | Empty secret permits anonymous mutations; use shared fail-closed constant-time verifier. | Recovered repair; isolated auth regressions required. |
| SYS-02 | High | Dashboard property_search.py | Provider failure fabricates owner, value and property; return genuine unavailable/error/empty. | Recovered repair; fault regressions required. |
| SYS-03 | High | Dashboard calls.py, dashboard/page.tsx | Call UUID used as Sophia UUID; resolve exact provider call metadata; deny ambiguous links. | Recovered repair; earlier 2 SQL mapping checks passed; current rerun required. |
| SYS-04 | High | Sophia store, realtime stream hooks | Stale signals/context/dedup survive identity changes; reset by session, reject unrelated events. | Recovered repair; type/lint/build pass. |
| SYS-05 | High | Dashboard dashboard/page.tsx | Invented KPI trend arrays; remove fabricated history. | Recovered repair; type/lint/build pass. |
| SYS-06 | Medium | Six list pages and dashboard | Overlap, stale async responses, swallowed errors; existing TanStack Query cancellation and explicit failures. | Recovered repair; type/lint/build pass. |
| SYS-07 | High | Dashboard services/api.ts | Arbitrary absolute destinations get bearer token; reject non-service paths/redirects, bound request/refresh, release queue in finally. | Recovered repair; fault tests required. |
| SYS-08 | Critical | Dashboard package-lock.json | Baseline 1 critical and 4 high runtime advisories; compatible graph upgraded to Next 16.4/ESLint 9 and patched sharp. | Recovered audit/build required; earlier graph zero advisories. |
| SYS-09 | Critical | Dashboard tests/conftest.py | Hardcoded personal database reset/Homebrew path; require explicit disposable test DSN and portable SQLAlchemy reset. | Recovered repair; four rejection cases pass; full suite requires disposable PostgreSQL. |
| SYS-10 | High | REI/dashboard ingestion boundary | Prefix mismatch, false acknowledgements, duplicate side effects and cross-database IDs. | Open: versioned persisted receipts, entity map and replay/fault checks. |
| SYS-11 | High | Dashboard ingest.py / sophia_bridge.py | Latest lead session receives unrelated transcript; model classification can trigger follow-up without governance/idempotency. | Open: exact binding, approval and deduplication. |
| SYS-12 | High | Dashboard migrations/models | Fresh install/provider enum/registration drift unverified. | Open: full PostgreSQL migration head/upgrade and independent concurrency testing. |
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
| SYS-24 | Critical | REI context_tracker.py | STOP persistence receipt ignored; fixed success speech on failure. | Recovered repair; prior 1395 tests passed before reset; current rerun required. |
| SYS-25 | High | Dashboard handoff/call mutation identity | Caller-selected operator attribution and read-only roles mutating calls. | Recovered role/identity/participant ownership repair; six independent handoff rejection cases pass. |
| SYS-26 | High | Full database harness | Embedded adapter loses transaction/error behavior; cannot count suite as green. | Open: disposable real PostgreSQL/Redis CI. |
| SYS-27 | Medium | Visual audit | Local server inaccessible; managed browser timed out for hours and reset workspace. | Blocked: supported screenshot/keyboard/mobile/contrast testing. No visual grade. |
| SYS-28 | High | Production voice/providers | Simulations do not prove accents/noise/muffled audio/duplex/hearing access, recovery, schedules, callbacks or durable volumes. | Open: approved real-call corpus, latency/turn metrics, provider outages and rollback drills. |

## Checklist

- [x] Architecture/inventory and ten-product desk research established before initial repairs.
- [x] Confirmed findings, root causes and required verification recorded.
- [x] Recovery commits preserve restored code; rerun verification proceeds against those files.
- [ ] Full backend suite, complete cross-project integration and migration gates green.
- [ ] Screenshot-backed visual design contract and complete redesign.
- [ ] Independent complete second audit against all original findings.
- [ ] Real phone and production infrastructure gates.

Nothing deployed, merged or connected to live callers. An overall A grade is not justified.
