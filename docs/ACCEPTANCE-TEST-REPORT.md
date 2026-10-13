# A-level acceptance campaign — October 11, 2026

**Local regression: 1,303 passed, zero failed, four dependency deprecation warnings. Live voice acceptance: blocked. The system has not earned an A.** This campaign found and repaired additional failure-reporting and approval defects. No calls were placed, messages sent to real recipients, changes deployed, or PR merged.

## Results

| Campaign | Result | What it establishes |
|---|---|---|
| Complete backend regression after repairs | 1,303/1,303, 30.27 seconds | Local mocked and deterministic contracts; not production success |
| Initial targeted recovery, workflow, conversation and accessibility tests | 397/397 | Existing recovery and policy behavior survived |
| New failure-path cases | 21/21 after fixes | Persistence failure, missing lead/operator, explicit approval decisions, stale/no-row resolution, server actor, unique/keyed replies, failed transfer and truthful STOP |
| Tests against the previous implementation | 11 failures in the initial 12-case group, plus two STOP failures | Reproduced defects before modifying their implementations |
| Dashboard HTTP campaign | 30/30 | Auth, error, response and timeout behavior against local fixtures |
| Embedded PostgreSQL scheduling/recovery campaign | Pass | Reservation idempotency, collisions, availability, generation-owned callback claims, event deduplication, stale events, rebooking reminder reset, due/type filters and anonymous denial |
| One-minute-window conversation replays | 33/33 | Eleven scripted scenarios in three text variants; no model responses or audible conversations |
| Actual synthetic PCM through installed Silero VAD | Speech detected in 60/65; four noise/silence controls stayed quiet | Five synthetic voices, thirteen conditions each; no word-recognition or human-accent claim |
| Static checks | Backend and new-test critical/unused-import lint pass; all tests critical lint pass; compile, whitespace and 129-package dependency compatibility pass | Broader test-directory unused-import lint still finds 15 existing issues |

The VAD rerun reproduced all five failures under sharp 300–3400 Hz telephone filtering. Clean speech and actual 8-kHz PCMU round trips pass. This is an unresolved speech-start gap, not proof every telephone call fails. No live Deepgram transcript fallback was measured for those five samples. Lowering VAD thresholds without a representative real-call/noise corpus could introduce false interruptions; calibration remains required.

Earlier long-window evidence remains 15 synthetic state runs at 3, 5, 10, 20 and 50 virtual minutes, passing 195/195 probes. Those long runs were not repeated in this campaign. They use authored utterances and virtual timestamps, not sustained model speech. This campaign's model-generated conversations and real phone recordings both equal **zero**. Prior whole-backend combined coverage was **31.6%**; coverage was not recalculated here.

## Repairs made during this campaign

- Call ending no longer reports a lead stage update after a write error or without a bound lead. A database update returning no changed row now fails verification.
- Operator unavailability, unsuccessful SMS acceptance, failed query persistence, polling errors and timeout all deny approval. Requests are saved before delivery is attempted. Provider acceptance remains distinct from delivery or a human answer.
- Operator query IDs use UUIDs rather than seconds. Replies must name the exact query ID, target a pending request and arrive within its 30-second window. The previous latest-global-query routing could attach one operator answer to another caller.
- Approval creation fails on an unconfirmed write. Duplicate requests must refer to a current, pending, unexpired request.
- Approval resolution requires an explicit approved/rejected decision. Updates conditionally match an unexpired pending request; missing/expired/already-resolved rows cannot produce success. The API reports conflicts and persistence errors and records the server's dashboard actor instead of caller-supplied attribution.
- Removed an unused approval helper that could grant call permissions after failed persistence without call binding or expiry. Approval-to-live-permission delivery remains an open integration gap; removal is containment, not completion of that workflow.
- STOP always ends the current call and blocks subsequent actions. If the number is unavailable or DNC/lead suppression writes fail, the response does not promise permanent removal. Durable recovery of failed suppression still needs implementation and verification.
- Corrected scenario examples that promised to increase volume or make scheduling changes with no corresponding tool. Cancellation/rescheduling now explicitly remain unperformed pending human handling.

## Six acceptance gates

| Gate | Decision now | Required to pass |
|---|---|---|
| Real caller understanding across accents/noise/echo/muffling | Not passed; acoustic gap reproduced | Consented recordings across representative voices and conditions; measure recognition of names, prices, dates and consent, plus unwanted interruptions and repair success |
| Actual 1/5/10/20-minute conversations | Blocked | Staging model/STT/TTS access; recorded generated dialogue scored for relevance, correction retention, memory, empathy and pressure; measure timing and speech quality |
| Complete appointment/callback/transfer lifecycle | Partial | Booking/callback local contracts pass. Implement authenticated cancel/reschedule tools and reminder-state integration; verify real provider outcomes, missed transfers and rescheduled follow-up |
| Operator approval and verified offers | Partial | Wire persisted, call/action-bound, expiring approval decisions into live permissions; test approval, rejection, expiry, concurrent calls and pricing limits end to end |
| Durable recovery | Partial | Add durable post-call/suppression outbox and reconciliation, then kill workers and interrupt real Redis/Postgres/provider connectivity; local PGlite serializes requests and does not establish independent-backend concurrency |
| Recorded acceptance and follow-through | Blocked | Controlled test number, staging providers, recordings and verified database/provider outcomes; independent listening review and no false completed-action claims |

No configured Anthropic, Deepgram, Cartesia/voice ID, SignalWire, Supabase or Redis staging credentials were found in the environment or the checked project environment files. This blocks real model/audio/provider tests. It is not a passing result and does not establish that production itself lacks configuration.

The previous published repair commit cc19b38613f13244c50e570c0c83e2492499c210 passed hosted CI run 38157653564. The repairs in this report require a new hosted run after publication. The repair PR remains a draft: https://github.com/Lavish213/REI-AGENT/pull/1.

## Evidence

- [Full backend regression](test-evidence/acceptance-pytest.txt)
- [Pre-repair adversarial failures](test-evidence/acceptance-red.txt)
- [Pre-repair STOP failures](test-evidence/acceptance-stop-red.txt)
- [Dashboard campaign](test-evidence/acceptance-dashboard.txt)
- [Embedded database campaign](test-evidence/acceptance-database.txt)
- [Conversation replay output](test-evidence/acceptance-replays.json)
- [Acoustic results](test-evidence/acceptance-acoustic.json)
- [New executable regressions](../tests/test_acceptance_failures.py)
