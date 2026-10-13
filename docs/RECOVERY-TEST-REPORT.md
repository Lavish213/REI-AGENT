# Recovery test and repair report

The recovery checkpoint passes **1,046 Python tests**, **30 dashboard HTTP checks**, and the PostgreSQL migration/recovery contracts. Real Redis contention admits exactly three calls in each of thirty rounds of 256 concurrent attempts. The expanded ledger contains all 129 original findings plus 15 new recovery findings. **This project is not established as A-grade.** The ledger still has 20 open and 17 partial findings, and the environment has no live voice-provider, Redis, or Supabase credentials.

The later conversation campaign is documented in [CONVERSATION-REPAIR-REPORT.md](CONVERSATION-REPAIR-REPORT.md).

## Measured results

| Check | Result and scope |
|---|---|
| Entire backend | 1,046 passed, four dependency deprecation warnings; coverage run took 22.96 seconds |
| Coverage | 30.6% statements, 20.6% branches, 28.3% combined across all 145 backend files; previous combined coverage was 26.3% |
| Provider HTTP contracts | 25 tests: JSON/XML acknowledgments, missing/poisoned IDs, 400/401/403/422/429 rejection, 500/502/503/504 uncertainty, connect/read/write timeouts, transport loss, duplicate-dial prevention and atomic expiry cleanup |
| Actual Pipecat execution | Four chunk sizes execute worker/runner, sentence cleanup, synthetic PCM, PCMU serialization and validated stream identity; permanent synthetic speech failure cancels the worker |
| Local Redis | Real server, 7,680 concurrent admission attempts, owned renewals, expired/stale rejection, and server termination; unavailable capacity denies admission |
| Embedded PostgreSQL | All three containment/scheduling/recovery migrations; repeat booking, overlaps, cancelled rebooking, reset reminder flags, unique callback generation, stale worker completion, opt-out filtering, 100 repeat provider events, stale/terminal status preservation, cross-lead denial and anonymous denial |
| Dashboard HTTP | 30 checks passed again using the built local Next server and mock backend, including authentication, uploads, concurrent requests, status preservation and deadlines |
| Static checks | Python compilation, critical/unused-name lint, dependency compatibility and patch whitespace pass |
| Hosted automation | Added GitHub Actions backend/database/dashboard regression workflow with read-only repository permissions and fake configuration; hosted run 38152958585 succeeded on recovery commit 5a5ef41; later conversation changes require their own run |

Evidence: [Python run](test-evidence/max-pytest.txt), [database recovery](test-evidence/database-recovery.txt), [dashboard HTTP](test-evidence/dashboard-http.json), [whole-backend coverage](test-evidence/backend-coverage.json), [all findings](VOICE-AUDIT-LEDGER.md).

## Repairs

- Claimed callbacks and follow-ups now require a unique generation. An expired worker cannot clear a newer claim, and missing ownership cannot dial. One failed claim, call, or completion no longer abandons the rest of the batch.
- A PostgreSQL event ledger counts each provider call once, locks lead state, preserves terminal/voicemail outcomes, and prevents older calls overwriting the current call. Durations retain the greatest observed value.
- Outbound media renews its owned Redis lease every 30 seconds. Three consecutive failures cancel the media pipeline. Calls have a 1,200-second maximum by default, configurable from 60 to 3,000 seconds.
- Lost or malformed provider acknowledgments and server failures retain the dial lease and return `requires_reconciliation`. They do not claim rejection or allow immediate duplicate dialing. Automatic reconciliation is still missing.
- Active-call lookup no longer removes expiration evidence before atomic ownership-map cleanup. It detects the actual lead as well as global capacity.
- Permanent provider errors cancel the Pipecat worker instead of continuing with an unusable service. The pipeline uses the current installed worker/runner API rather than deprecated aliases.
- Outbound prompt prices convert integer cents once. The live registry retains inbound context through the call and registers outbound context, with property details available to the operator.
- Reminders use the actual Pacific date, require a matching confirmed reservation, and exclude suppressed/cancelled/stale bookings. New reservations reset reminder flags. Follow-up no longer fabricates attendance and stops after 48 hours.
- Recording persistence failures return a retryable server error instead of acknowledging success. Touched database operations use the central wrapper and worker threads.
- QA tool metrics now match stored metrics. Invalid, nonfinite, Boolean, missing and out-of-range scores are rejected. Inapplicable metrics may be null; the overall score averages applicable metrics. QA no longer describes Sophia as a human of a fabricated age or infers acoustic quality from text.
- Ordinary call teardown awaits bounded QA and intelligence work. It no longer abandons those detached tasks at disconnect. This does **not** make post-call work durable after process termination.

## What still prevents an A

| Gate | Remaining work |
|---|---|
| Voice quality | Configure providers in staging and run the 50 recorded, controlled calls in VOICE-REPAIR.md. Measure audible first response, turn completion, interruption recovery, noise/echo/accent accuracy, English/Spanish switching, pronunciation and long conversation retention. Synthetic PCM contains no human speech. |
| Workflow correctness | Finish operator query/approval/reply wiring, changed/cancelled bookings, multiple properties, long-call corrections, and discovery shortcuts. Verify callbacks against a real provider and actual calendar state. |
| Crash recovery | Durable post-call queue/outbox, external delivery reconciliation, provider-call reconciliation after lost acknowledgments/pre-bind callbacks, Redis data loss, worker termination and abandoned leases. Retaining uncertain capacity is containment, not recovery. |
| Database and deployment | Complete missing clean-database baseline; apply every migration to staging; test independent PostgreSQL connections, authorization/tenant boundaries and multi-worker locking. Embedded PGlite serializes its requests and cannot prove independent database-backend contention. |
| Remaining integrations | Repair and test acquisition/enrichment, cash buyers, bounded comps cache, signed outgoing unsubscribe links, opt-out persistence recovery, and API failure visibility. All unresolved items remain in the ledger. |
| Verification breadth | Raise coverage by executing the uncovered workflows, not by multiplying parameters. The 28% CI floor guards against regression; it is not an A-grade threshold. |

No seller was called or messaged, no production records were modified, and nothing was deployed. Missing credentials prevent live-provider measurements here; they do not account for the remaining code and workflow gaps.

## Staging rollout

Drain active calls and claimed jobs. Review and apply tenant/suppression, scheduling, then `20261012_call_recovery.sql`. Restart designated workers together so older workers cannot finish newer generation-owned claims. Keep outbound disabled until recorded acceptance passes. Regrading existing call transcripts is necessary to replace previously mislabeled QA fields; this repair does not rewrite historical scores.

## Reference checks

Provider lifecycle behavior was checked against the installed Pipecat source and its [service event documentation](https://docs.pipecat.ai/server/utilities/service-events). The [worker reference](https://reference-server.pipecat.ai/en/latest/api/pipecat.pipeline.worker.html) describes error handling; local tests verify the pinned version's behavior. The [official Cartesia client](https://github.com/cartesia-ai/cartesia-python) documents streaming output, but no actual Cartesia request or pronunciation result was measured.
