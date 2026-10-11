# Voice reliability repair and release requirements

This branch repairs the live voice path, scheduling, dialing controls, access boundaries, and dashboard integration. It is a tested repair candidate, not a production A-grade certification. No deployment, real seller calls, provider-paid conversations, or actual delivery tests were performed. Naturalness, timing, and turn taking still require recorded telephone calls.

## What changed

- The pipeline starts without the shadowed brief-loader crash. SignalWire media uses the real stream SID, validates PCMU 8 kHz boundaries, and authenticates scoped media sessions.
- Streaming answers now flush at sentence boundaries. Interruption resets stale text, buffers are bounded, and artificial thinking delays, per-packet EQ, repeated breaths, broken mute routing, and extra speech rewriting are removed from the live path.
- Silero VAD and local Smart Turn detect turn completion. Short meaningful replies remain usable. Spanish STT settings reach Deepgram. Cartesia selection reaches the real TTS service; Deepgram remains an explicit fallback.
- The seller's first statement, property details, seller memory, and current call state reach the model. A separate transcript journal preserves conversation instead of reconstructing it from an altered LLM context.
- Natural, concise, truthful automated-agent instructions replace contradictory identity and filler guidance. HOT/WARM dispositions no longer automatically wrap a call before an appointment or callback is saved.
- Tools bind to the authenticated call's seller and lead. Missing or unsafe intel and missing action permissions block side effects. Permission levels apply to specific actions. Failed sends, invalid appointments, unavailable voicemail actions, and failed saves cannot be announced as successful.
- Appointments require seller confirmation, future valid local times, and owner-approved availability. PostgreSQL reservations reject overlaps and are idempotent. Callback tools persist exact timezone-aware due times; vague times require clarification.
- Redis atomically limits outbound concurrency and duplicate leads, failing closed if unavailable. Closed leads, future callbacks, paused campaigns, DNC checks, retries, and due-task claims now govern dialing.
- Admin APIs and dashboard routes require authentication. Provider webhooks require signatures. Dashboard ingestion requires its own secret. Browser clients no longer receive the Supabase service key or backend operator token.
- The dashboard uses an authenticated server proxy, has a single root route, reports real provider/campaign states, and passes TypeScript/build/lint checks. Dependencies are pinned with a Python hash lock.
- Automatic post-call HOT/WARM texts were removed because they could promise an unbooked walkthrough and bypass call-bound delivery checks. Explicit tool confirmations remain the source of seller next steps.

## Verification

| Check | Result | What it establishes |
|---|---|---|
| Python suite | 352 passed; 7 deprecation warnings | Regression and focused integration behavior |
| Actual pipeline construction | Passed without provider network requests | Real services and flattened processor ordering construct |
| Interruption stress | 1,000 resets passed | No stale sentence-buffer output after interruption |
| Dial admission stress | 100 concurrent attempts; exactly 3 admitted | Atomic limit enforcement in Redis-compatible Lua test runtime |
| PostgreSQL scheduling migration | Passed using PGlite | Reservation idempotency, overlaps, approved availability, due claims, task types, anonymous denial |
| Dashboard | Build passed; lint zero errors/warnings | Next 16 compilation and static checks |
| Dependencies | Compatible; hash lock generated | Installed Python dependency consistency |
| Patch whitespace | Passed | Clean patch formatting |

The Redis stress test uses fakeredis with Lua, not a production Redis cluster. The migration test uses a minimal baseline fixture and PGlite, not the existing Supabase database. The pipeline test does not measure real provider speech quality, remote playback, or telephone latency. Dashboard builds require configured Supabase URL/service-key values; verification used nonproduction placeholders. The updated master was merged into this repair branch; its containment rules and removal of committed seller exports are preserved. Both migrations execute together in the test fixture, and service-role update/delete on suppression evidence are denied.

Seven warnings originate from pinned Pipecat/Supabase dependencies and the deprecated PipelineTask API.

Reproduce from the repository root:

```sh
uv venv --python 3.11
uv pip install --python .venv/bin/python --require-hashes -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m pytest -q
npm ci --prefix tests
npm run test:database --prefix tests
npm ci --prefix dashboard
npm run build --prefix dashboard
npm run lint --prefix dashboard
```

## Deployment setup

Review and apply `supabase/migrations/20260911_tenant_and_suppression.sql` before `supabase/migrations/20261011_voice_scheduling.sql` to a staging copy first, after reviewing existing table shapes, roles, and policies. This migration is additive for scheduling but deliberately revokes anonymous access across public tables. Existing clients relying on anonymous table access must be migrated. It assumes base `leads` and `followups` tables already exist; it does not complete the repository's missing clean-database bootstrap.

| Component | Required configuration |
|---|---|
| Backend database | `SUPABASE_URL`, server-only `SUPABASE_SERVICE_KEY` |
| Telephone provider | `SIGNALWIRE_SPACE`, `SIGNALWIRE_PROJECT_ID`, `SIGNALWIRE_TOKEN`, `SIGNALWIRE_PHONE`, `SIGNALWIRE_SIGNING_KEY` |
| External callback origin | `PUBLIC_URL` set to exact public HTTPS origin; proxy/path behavior must preserve signature URL |
| Speech recognition | `DEEPGRAM_API_KEY`; `DEEPGRAM_MODEL` defaults to nova-3 |
| Language model | `ANTHROPIC_API_KEY`; optional `VOICE_LLM_MODEL` |
| Cartesia speech | `VOICE_TTS_PROVIDER=cartesia`, `CARTESIA_API_KEY`, actual `CARTESIA_VOICE_ID`; optional `CARTESIA_MODEL` |
| Deepgram speech fallback | `VOICE_TTS_PROVIDER=deepgram`; optional `DEEPGRAM_TTS_MODEL` |
| Dial admission | `REDIS_URL` shared by all callers; `OUTBOUND_ENABLED=false` until release approval |
| Tenant ownership | `TENANT_ID` must match the persisted lead tenant; apply the tenant/suppression migration before scheduling migration |
| Operator backend access | Strong server-only `OPERATOR_API_TOKEN`, or verified Supabase operator/admin app metadata |
| Dashboard | `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`, `BACKEND_URL`, matching `OPERATOR_API_TOKEN`, `NEXT_PUBLIC_SUPABASE_URL`, server-only `SUPABASE_SERVICE_KEY` |
| Ingest | Matching `KARPATHYS_WEBHOOK_SECRET` in producer and dashboard |
| CORS if needed | Exact dashboard origins in `DASHBOARD_ORIGINS` |
| Background scheduling | `ENABLE_BACKGROUND_JOBS=false` on web replicas; enable only on one designated process |

Configure only one background-job process. The callbacks and followup claims have database leases, but other legacy schedules are not comprehensively distributed-job safe. Enabling background jobs on every web replica remains unsafe.

The current master containment rules are preserved: missing tenant, missing/unsafe packet, missing or expired action permission, and disabled outbound execution deny side effects. The packet permission registry now includes callback and availability tools. Approved packets need `read_availability` for `get_available_appointments`, `book_appointment` for appointment/callback/followup actions, and the exact corresponding send/transfer/operator permission for those actions. Do not automatically grant every action to make calls pass.

Add owner-approved walkthrough availability through authenticated `POST /api/appointments/availability` with offset-aware `starts_at` and `ends_at` timestamps. Slots must be future dates lasting 15 minutes to three hours. Without approved slots, the agent must offer a callback or operator assistance rather than invent availability. The new table is an internal availability calendar; Google/Outlook calendar sync is not implemented.

Do not place service keys or operator tokens in `NEXT_PUBLIC_*` variables. Verify provider webhook signatures against real callbacks in staging before allowing dialing. SendGrid event signatures require the configured public verification key; test the provider's actual signed payload and unsubscribe link generation end to end.

## Remaining work before an A

The complete original findings and statuses are in [VOICE-AUDIT-LEDGER.md](VOICE-AUDIT-LEDGER.md) and [VOICE-AUDIT-FINDINGS.json](VOICE-AUDIT-FINDINGS.json). Addressed entries still require deployment verification. Open items were not silently removed or represented as fixed.

Release blockers and important residual gaps include:

1. Complete a clean database bootstrap and verify every referenced legacy table/column/RPC against the production schema. Verify all RLS changes against existing policies and authenticated roles.
2. Finish the human operator query/approval/reply path with durable requests, action-scoped approvals, expiry, idempotency, and verified delivery. A 30-second wait on a disconnected reply flow is not a working escalation system.
3. Make post-call grading, intel refresh, transcripts, provider status retries, and notifications durable with retryable jobs. Remove remaining blocking database/provider operations from async paths.
4. Repair the still-open acquisition integrations: missing auto-enrichment/cash-buyer functions, partial deployed scout cycle, property-schema disagreements, residential filtering, and cache bounds.
5. Verify intel freshness/safe-for-live-call/versioning, atomic approvals, offer ceilings and dollar/cents contracts against realistic records. Regex output filters are not a complete protection against split or paraphrased prohibited speech.
6. Finish live-call registry/event identifiers and truthful metrics. Store actual latency/interruption measurements; present explicit errors wherever APIs currently look like an empty state.
7. Add provider delivery reconciliation, reminder/attendance event truth, and durable opt-out recovery. Finish outgoing signed unsubscribe links, not just token verification.
8. Protect concurrency leases from stale status callbacks releasing a newer attempt; implement owned leases and heartbeat/maximum-call duration. Media session tokens remain replayable inside their short validity window; bind and consume them atomically if exposure is possible.
9. Remove discovery-stage turn-count shortcuts that can advance without required facts. Test corrections, changed appointments, cancellations, multiple properties, and repeated requests throughout long conversations.
10. Prove performance with real Redis/PostgreSQL and recorded telephony under controlled load. The current tests do not establish sustained production throughput or acoustic conversation quality.

## Recorded-call acceptance gate

Use controlled consenting test callers and retain audio, provider events, tool outcomes, and timestamps. Start with a staging number and three simultaneous calls. At minimum, cover 50 scenario calls across English and Spanish, fast/slow speakers, quiet pauses, background noise, speakerphone echo, accents, interruptions, and provider failures. These are proposed release targets, not measured results:

| Behavior | Required acceptance evidence |
|---|---|
| Opening | Exactly one clear opening; first seller reply retained; no enrichment-induced long silence |
| Turn completion | Caller can finish a thought and pause; short yes/no/number replies work; false interruptions measured and reviewed |
| Real barge-in | Stale speech stops promptly; next answer addresses the interruption; no old text/audio continues |
| Latency | Measure end-of-user-turn to first audible speech; target p95 under 1.5 seconds under expected load; record all long-tail stalls |
| Conversation | One useful question at a time; no forced wrap on HOT/WARM; correct facts survive 15+ turns and corrections |
| Appointment | Only approved slots; seller confirmation required; no overlaps; timezone/DST correct; cancellations/reschedules verified |
| Callback | Exact agreed time saved; no early/duplicate dial; failed dial retried honestly; campaign pause/DNC respected |
| Delivery | Provider accepts and later delivers confirmations, or the UI and agent report uncertainty/failure accurately |
| Truth and safety | Automated identity answered honestly; immediate opt-out; no invented price, memory, booking, delivery, or availability |
| Failure recovery | STT/TTS/LLM disconnects, websocket stalls, Redis outage, DB outage, retries and worker restarts terminate or recover without duplicates |

A voice can sound natural only after listening to these recordings and adjusting the actual selected voice, VAD, endpointing, and response length against measured failures. Zero interruptions is not an appropriate universal setting: genuine caller interruptions must stop the agent. Distinguishing those from brief backchannels requires real audio evidence.

## Research used

The repair follows Pipecat's turn-management and streaming service architecture and SignalWire's stream protocol. Working systems such as LiveKit treat turn detection, real interruptions, false interruptions, and recovery as measured runtime behavior rather than prose instructions alone. No LiveKit transport was added; SignalWire remains the telephone provider.

- [Pipecat turn strategies](https://reference-server.pipecat.ai/en/latest/api/pipecat.turns.user_turn_strategies.html)
- [Pipecat implementation examples](https://github.com/pipecat-ai/pipecat)
- [SignalWire stream protocol](https://signalwire.com/docs/compatibility-api/cxml/reference/voice/stream)
- [SignalWire webhook verification](https://signalwire.com/docs/server-sdks/reference/python/core/security/validate-webhook-signature)
- [Cartesia realtime websocket speech](https://docs.cartesia.ai/api-reference/tts/websocket)
- [LiveKit turn detection](https://docs.livekit.io/agents/build/turns/)
