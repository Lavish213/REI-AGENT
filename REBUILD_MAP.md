# Rebuild Map — Gate 2

**Status:** proposed. Depends on `REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md`, which
is itself unratified.

**Method:** every file was read off disk on 2026-09-07, not recalled. Line
counts and diffs are measured. Where I could not verify a claim, it is marked
`[UNVERIFIED]` rather than asserted.

**Granularity:** `REI-AGENT`, `Sophia-Agent` and `bob-intelligence-` are
classified **file by file**, because those three are merging into one trunk.
`The-Dashboard` is classified **module by module**, because it stays a separate
deployable and its files do not move — classifying 670 files individually would
be volume, not information.

---

## 0. Assumptions this map runs on

The §18 **[OPEN]** items are not decided. Rather than block, this map proceeds
on the recommendations, stated here so they are easy to overrule:

| Assumed | If you decide otherwise |
|---|---|
| `REI-AGENT` is the trunk | Every `MOVE` row reverses direction; the map survives, the arrows flip |
| `Sophia-Agent` stays frozen and running as fallback | Its rows become `DELETE` instead of `LEGACY` |
| Karpathys stays a separate deployable, no shared DB | §7 collapses into the trunk and Gate 3 merges into Gate 4 |
| Sophia makes no binding offer in V2 | `voice/tools.py` needs an offer-authority gate it currently lacks |

Nothing below is committed to code. This is a plan.

---

## 1. Classification vocabulary

| Tag | Means | Obligation |
|---|---|---|
| `KEEP` | Correct as written, stays where it is | Regression test before it counts as done |
| `HARDEN` | Right idea, unsafe or untested as written | Named defect must be fixed and tested |
| `MOVE` | Correct, lives in the wrong repo | Arrives with its tests or it does not arrive |
| `ADAPT` | Two versions exist; merge the better parts | Merge decision recorded per function |
| `REPLACE` | Rewrite against the V2 contract | Old file deleted in the same commit |
| `DELETE` | Dead, empty, or duplicated | Deleted, not commented out |
| `LEGACY` | Frozen, still running, not developed | Tagged and left alone |

**`DELETE` means deleted.** A duplicate left in place "just in case" is the
failure mode this whole exercise exists to end.

---

## 2. The merge rule

Reading all four repos, the split is cleaner than expected, and it is not
"one repo wins":

> **`REI-AGENT` wins the runtime.** Voice pipeline, API, workflow engine, scout
> scrapers, comps, intel assembly. It is larger, integrated, and has the
> processor stack.
>
> **`Sophia-Agent` wins the safety layer.** Compliance, canonical intake,
> validation, skip trace, voicemail, dispo, heartbeats, prioritizer — and 426
> tests, against `REI-AGENT`'s 257.
>
> **`The-Dashboard` wins authority.** Governance, approvals, event store,
> security, and the session/turn ledger.
>
> **`bob-intelligence-` wins nothing** as a repo, but may win individual
> function bodies. That is decided per module in §8, not per repo.

`REI-AGENT` is bigger in almost every overlapping file. **Bigger is not a
merge criterion.** The compliance engine is the case in point: `REI-AGENT`'s is
75 lines, `Sophia-Agent`'s is 85 plus a 119-line timezone module, and the
smaller one is the one that would get you sued.

---

## 3. What mapping turned up

Six findings that change the order of work. All are defects in the trunk.

### 3.1 `_check_dnc` fails open — TCPA

`backend/compliance/compliance.py:26-33`. On any database exception it returns
`False`, which reads as "not on the Do Not Call list", which reads as
"allowed to call". A Supabase blip becomes a call to a DNC-listed number.

`Sophia-Agent`'s equivalent fails closed. **This is the single highest-priority
line in the map.** Spec invariant #5: governance failures deny.

### 3.2 Calling hours assume every seller is in Pacific

`compliance.py:17-23` hardcodes `America/Los_Angeles` and permits 9–21. Five
other modules hardcode Pacific the same way (`voice/outbound.py:17`,
`voice/tools.py:16`, `voice/appointment_scheduler.py:13`, `alerts/sms.py:5`).

`CALLING_HOURS_END=21` Pacific is **midnight Eastern**. TCPA's window is 8am–9pm
**in the called party's timezone**. `Sophia-Agent/backend/compliance/timezones.py`
maps area code → IANA zone with a strict two-zone fallback for unknown codes.
That module is not optional.

### 3.3 The dashboard's ingest routes have no authentication

`dashboard/app/api/ingest/{call,turn,ended,complete}/route.ts` write straight
into Supabase `call_events`. Grepped for any secret, header, or auth check
across all four: **none**. Anyone who can reach the deployed URL can inject
fabricated call events into the system of record.

Meanwhile `backend/karpathys/client.py:23` faithfully sends
`X-Karpathys-Secret` — to an endpoint that ignores it.

### 3.4 There are two different things called "Karpathys ingest"

`KARPATHYS_URL/api/v1/ingest/*` resolves to either:

- `The-Dashboard/backend/api/routes/ingest.py` — real service, checks the secret,
  dedupes on `provider_call_id`; **or**
- `REI-AGENT/dashboard/app/api/ingest/*/route.ts` — no auth, no dedupe, writes
  to the same Supabase the backend uses.

Which one is live depends on an environment variable. The second violates the
"no shared database" rule outright. **Gate 2 must establish which is deployed
before Gate 3 hardens the wrong one.** `[UNVERIFIED]` — I cannot read the
deployed env from here.

### 3.5 The-Dashboard's ingest also fails open

`ingest.py:21`: `if _WEBHOOK_SECRET and x_karpathys_secret != _WEBHOOK_SECRET`.
If `KARPATHYS_WEBHOOK_SECRET` is unset, the condition short-circuits and every
request is accepted. A missing env var silently disables authentication.

### 3.6 No config layer, and events are lost silently

`REI-AGENT` has no `backend/lib/config.py`. **32 backend files read `os.environ`
directly**, so no startup check can tell you a required variable is missing —
see 3.5 for why that matters. `Sophia-Agent/backend/lib/config.py` exists and is
test-enforced by `test_env_example.py`.

Separately, `backend/karpathys/emitter.py` wraps all nine emit functions in
`try/except` + log. Karpathys down, slow, or misconfigured → the call proceeds
and the event is gone. Two immediate retries, no outbox, no dead letter,
nothing on either side that notices.

### 3.7 Sophia is triplicated too, not just Bob

The V2 spec recorded Bob existing in three places. Mapping found the same is
true of Sophia's conversation runtime:

- `REI-AGENT/backend/voice/` — the real Pipecat speech pipeline, 45 modules
- `Sophia-Agent/backend/voice/` — smaller, but owns voicemail and compliance
- `The-Dashboard/backend/sophia/` + `backend/calls/runtime/` — a session/turn
  state machine with governance wired into it

The third is **not** simply a duplicate — `sophia/turn.py` imports
`GovernanceEngine` and has an `awaiting_approval` state, which is exactly the
§14 authority model the other two lack. But all three define overlapping
`contracts`, `interruption`, `tools`, and trust/confidence signals. See §8.2.

---

## 4. `REI-AGENT` — the trunk (249 tracked files)

### 4.1 `backend/compliance/` — rebuild first

| File | Lines | Tag | Why |
|---|---|---|---|
| `compliance/compliance.py` | 75 | `REPLACE` | Fails open (3.1), Pacific-only (3.2). Replaced by Sophia-Agent's engine |
| `compliance/COMPLIANCE.md` | — | `ADAPT` | Merge Sophia-Agent's TCPA/DNC notes |
| *(missing)* `compliance/timezones.py` | — | `MOVE` ← Sophia-Agent | Area-code → IANA, strict fallback |

### 4.2 `backend/voice/` — 45 modules, the trunk's real asset

| File | Lines | Tag | Why |
|---|---|---|---|
| `voice/agent.py` | 1129 | `HARDEN` | Pipeline is sound; takes direct side effects that must route through the Orchestrator. Split — 1129 lines is not reviewable |
| `voice/tools.py` | 864 | `HARDEN` | Needs offer-authority gate (§10.1) and execution-ledger rows per §17.2 |
| `voice/webhook.py` | 418 | `HARDEN` | SignalWire signature verification unconfirmed `[UNVERIFIED]` |
| `voice/outbound.py` | 411 | `HARDEN` | Hardcodes Pacific (3.2); must call `may_contact()` |
| `voice/outbound_webhook.py` | 412 | `HARDEN` | Same |
| `voice/preloader.py` | 273 | `ADAPT` | Merge Sophia-Agent's unknown-caller lead creation |
| `voice/simulator.py` | 274 | `KEEP` | Feeds Gate 9 |
| `voice/context.py` | 59 | `ADAPT` | Sophia-Agent's is 202 lines and has caller-awareness + call-brief builders the trunk lacks |
| `voice/processors/context_tracker.py` | 640 | `HARDEN` | Split; single largest processor |
| `voice/processors/ai_identity.py` | 38 | `HARDEN` | FCC Feb-2024 AI-voice disclosure — must be unconditional, not model-discretionary |
| `voice/processors/compliance_output_filter.py` | 84 | `KEEP` | |
| `voice/processors/fair_housing.py` | 57 | `KEEP` | |
| `voice/processors/input_guard.py` | 50 | `KEEP` | |
| `voice/processors/interruption.py` | 43 | `ADAPT` | Reconcile with `The-Dashboard/backend/sophia/interruption.py` |
| `voice/processors/` — other 15 | — | `KEEP` | ai_softener, analysis_callbacks, backchannel, breath_injector, filler, humanized_latency, latency_tracker, phone_eq, room_tone, sentence_streamer, silence_detector, speed_tracker, stt_mute |
| `voice/turn_controller.py` | 76 | `ADAPT` | Reconcile with `sophia/turn.py` (§8.2) |
| `voice/trust_tracker.py` | 103 | `ADAPT` | Duplicates `sophia/metrics.py` signals |
| `voice/deal_heat_scorer.py` | 172 | `ADAPT` | Same |
| `voice/emotional_state_engine.py` | 123 | `KEEP` | |
| `voice/microstate_engine.py` | 124 | `KEEP` | |
| `voice/momentum_tracker.py` | 112 | `KEEP` | |
| `voice/resistance_tracker.py` | 172 | `KEEP` | |
| `voice/seller_profile_engine.py` | 173 | `KEEP` | |
| `voice/objective_engine.py` | 133 | `KEEP` | |
| `voice/fatigue_detector.py` | 86 | `KEEP` | |
| `voice/silence_handler.py` | 121 | `KEEP` | |
| `voice/speech_chunker.py` | 180 | `KEEP` | |
| `voice/geo_phrases.py` | 216 | `KEEP` | |
| `voice/memory.py` | 189 | `HARDEN` | Must become a MemoryFact reader per §8; no independent truth |
| `voice/call_brief_loader.py` | 33 | `HARDEN` | Must reject an expired StrategyPlan (§17.11) |
| `voice/call_state_cache.py` | 75 | `KEEP` | |
| `voice/appointment_scheduler.py` | 119 | `HARDEN` | Pacific-hardcoded (3.2) |
| `voice/runtime_orchestrator.py` | 160 | `HARDEN` | |
| `voice/prompt_budget.py` | 76 | `KEEP` | |
| `voice/providers.py` | 111 | `KEEP` | |
| `voice/events.py` | 94 | `REPLACE` | Must emit the §5 envelope |
| `voice/states/close.py`, `end_call.py` | 97 | `HARDEN` | STOP must be enforced outside the model (§17.12) |
| `voice/prompts/sophia_runtime.md` | — | `KEEP` | |
| `voice/prompts/sophia_legacy_runtime.md` | — | `DELETE` | Superseded |
| *(missing)* `voice/voicemail.py` | — | `MOVE` ← Sophia-Agent | AMD + voicemail scripts |
| *(missing)* `voice/post_call_intel.py` | — | `MOVE` ← Sophia-Agent | |

### 4.3 `backend/karpathys/` — the seam

| File | Lines | Tag | Why |
|---|---|---|---|
| `karpathys/client.py` | 45 | `HARDEN` | Reads `os.environ` at import (3.6); needs outbox-backed delivery |
| `karpathys/emitter.py` | 90 | `REPLACE` | Swallows every failure (3.6). Becomes an outbox writer |
| `karpathys/events.py` | 139 | `REPLACE` | Must emit the §5 envelope with actor, causation, idempotency key |

### 4.4 `backend/bob/` — see §8.1 for the three-way resolution

| File | Lines | Tag |
|---|---|---|
| `bob/call_planner/brief_generator.py` | 58 | `REPLACE` |
| `bob/call_planner/objective_selector.py` | 30 | `ADAPT` |
| `bob/call_planner/checkbox_selector.py` | 40 | `ADAPT` |
| `bob/call_planner/avoidances_builder.py` | 33 | `ADAPT` |
| `bob/call_planner/escalation_rules.py` | 30 | `ADAPT` |
| `bob/decisions/decision_logger.py` | 26 | `HARDEN` |
| `bob/events/bob_events.py` | 42 | `REPLACE` |
| *(missing)* `bob/prioritizer.py` | — | `MOVE` ← Sophia-Agent |
| *(missing)* `bob/worker.py` | — | `MOVE` ← Sophia-Agent |

### 4.5 `backend/contracts/`

| File | Lines | Tag | Why |
|---|---|---|---|
| `contracts/call_brief.py` | 44 | `HARDEN` | Best thing in the repo. Add `plan_id`, `issued_at`, `expires_at`, `confidence` → §9 StrategyPlan |
| `contracts/intel_packet.py` | 148 | `HARDEN` | Add provenance per fact (§17.9) |

### 4.6 `backend/scout/`

| File | Lines | Tag | Why |
|---|---|---|---|
| `scout/deduper.py` | 0 | `DELETE` | Empty file |
| `scout/scorer.py` | 316 | `ADAPT` | Reconcile with Sophia-Agent's 285-line version |
| `scout/parser.py` | 185 | `ADAPT` | Near-identical to Sophia-Agent's 186; diff and pick |
| `scout/cron.py` | 172 | `HARDEN` | No heartbeat; failures invisible |
| `scout/eviction_scraper.py` | 89 | `HARDEN` | CA CCP §1161.2 masks eviction records — confirm the source is lawful to use `[UNVERIFIED]` |
| `scout/court_scraper.py` | 214 | `KEEP` | |
| `scout/tax_scraper.py` | 166 | `KEEP` | |
| `scout/crmls_scraper.py` | 193 | `KEEP` | |
| `scout/cash_buyer_scraper.py` | 107 | `KEEP` | |
| `scout/social_scraper.py` | 93 | `KEEP` | |
| `scout/rss_scraper.py` | 83 | `KEEP` | |
| `scout/expired.py` | 142 | `KEEP` | |
| `scout/engagement.py` | 182 | `KEEP` | |
| *(missing)* `scout/intake.py` | — | `MOVE` ← Sophia-Agent | **The one canonical lead path.** Without it every scraper writes leads its own way |
| *(missing)* `scout/validate.py` | — | `MOVE` ← Sophia-Agent | |
| *(missing)* `scout/skiptrace.py` | — | `MOVE` ← Sophia-Agent | |
| *(missing)* `scout/stale_listings.py` | — | `MOVE` ← Sophia-Agent | |
| *(missing)* `scout/ingest.py`, `convert.py`, `reddit.py` | — | `MOVE` ← Sophia-Agent | |

### 4.7 `backend/alerts/` — all outbound must route through the Orchestrator (§13)

| File | Lines | Tag | Why |
|---|---|---|---|
| `alerts/ringless.py` | 158 | `HARDEN` | Ringless voicemail is legally contested; hard-gate behind consent + explicit enable |
| `alerts/drip.py` | 485 | `HARDEN` | Largest alerts module; no `may_contact()` |
| `alerts/speed_to_lead.py` | 252 | `HARDEN` | |
| `alerts/sophia_loop.py` | 228 | `HARDEN` | |
| `alerts/deal_blast.py` | 170 | `ADAPT` | Merge Sophia-Agent `dispo/matcher.py` |
| `alerts/sms.py` | 140 | `ADAPT` | Sophia-Agent's has hours + DNC checks this lacks |
| `alerts/email.py` | 309 | `ADAPT` | |
| `alerts/formatter.py` | 120 | `KEEP` | |
| `alerts/phone_pool.py` | 58 | `KEEP` | |
| *(missing)* `alerts/owner.py`, `followup.py` | — | `MOVE` ← Sophia-Agent | |

### 4.8 `backend/api/`

| File | Lines | Tag | Why |
|---|---|---|---|
| `api/main.py` | 254 | `HARDEN` | No startup config validation (3.6) |
| `api/routes/email_webhook.py` | 238 | `HARDEN` | Webhook auth `[UNVERIFIED]` |
| `api/routes/sms.py`, `sms_status.py` | 109 | `HARDEN` | SignalWire signature verification |
| `api/routes/workflow.py` | 311 | `HARDEN` | Triggers side effects without approval rows |
| `api/routes/health.py` | 93 | `ADAPT` | Merge Sophia-Agent worker-health |
| `api/routes/calls.py`, `leads.py`, `properties.py`, `offers.py`, `analytics.py`, `intel.py`, `live.py`, `evals.py` | 1091 | `KEEP` | |

### 4.9 `backend/lib/`, `qa/`, `comps/`, `evals/`, `workflows/`

| File | Lines | Tag | Why |
|---|---|---|---|
| `lib/db.py` | 1268 | `HARDEN` | Single largest file. Split by aggregate; it is where "Sophia holds CRM truth" lives |
| `lib/batchdata.py` | 404 | `KEEP` | |
| `lib/osm.py` | 495 | `KEEP` | |
| `lib/intel_assembler.py` | 199 | `KEEP` | |
| `lib/census.py`, `lib/zestimate.py` | 235 | `KEEP` | |
| *(missing)* `lib/config.py` | — | `MOVE` ← Sophia-Agent | **Blocks 3.5 and 3.6** |
| *(missing)* `lib/heartbeat.py` | — | `MOVE` ← Sophia-Agent | |
| `observability.py` | 201 | `KEEP` | |
| `qa/grader.py`, `metrics.py`, `transcript_intel.py` | 369 | `KEEP` | |
| `comps/calculator.py` | 132 | `ADAPT` | Sophia-Agent's is 137; diff MAO/ARV |
| `comps/cache.py`, `homeharvest.py`, `redfin.py` | 305 | `KEEP` | |
| `evals/eval_cases.py`, `eval_runner.py`, `eval_report.py` | 451 | `KEEP` | Advisory only — must never enter the decision path (§17.15) |
| `workflows/engine.py` | 265 | `HARDEN` | Must consult governance before acting |

### 4.10 Non-Python

| Path | Tag | Why |
|---|---|---|
| `dashboard/app/api/ingest/*` (4 routes) | `REPLACE` | **No authentication** (3.3); writes to shared Supabase |
| `dashboard/lib/supabase.ts` | `HARDEN` | Service key in a Next.js route |
| `dashboard/app/**` (12 pages, 1 component) | `ADAPT` | Merge Sophia-Agent's `/health`, `/reasoning`, `/discovered`, `/buyers`, auth middleware |
| `supabase/migrations/*` (13) | `KEEP` | Applied; forward-only |
| `tests/*` (10 files, 257 tests) | `KEEP` | |
| `scripts/*` (9 py, 2 csv) | `KEEP` | Never imported |
| `SOPHIA_*.md` (16 files) | `ADAPT` | Behaviour specs; reconcile against §12 |
| `docs/**` (6) | `KEEP` | |
| `AGENTS.md` | `ADAPT` | Missing the config.py and no-shared-DB rules |
| `.env.example` | `REPLACE` | Currently **empty**; 32 files read env vars |
| `Procfile`, `railway.json`, `requirements.txt` | `ADAPT` | Must gain the dialer/discovery workers |

---

## 5. `Sophia-Agent` — the donor (174 tracked files, 426 tests)

Everything here is either `MOVE` (into the trunk) or `LEGACY` (frozen where a
better version already exists in the trunk).

### 5.1 `MOVE` — arrives in the trunk with its tests

| File | Lines | Trunk destination | Why it wins |
|---|---|---|---|
| `backend/compliance/compliance.py` | 85 | `backend/compliance/` | Fails **closed**; checks hours + DNC + opt-out |
| `backend/compliance/timezones.py` | 119 | `backend/compliance/` | Recipient-timezone TCPA. Trunk has no equivalent |
| `backend/lib/config.py` | 80 | `backend/lib/` | Only declared-config layer in any repo |
| `backend/lib/heartbeat.py` | 37 | `backend/lib/` | Swallows its own failures by design |
| `backend/scout/intake.py` | 177 | `backend/scout/` | The one canonical lead path |
| `backend/scout/validate.py` | 172 | `backend/scout/` | Data-quality gate |
| `backend/scout/skiptrace.py` | 216 | `backend/scout/` | Phone blocking fails closed |
| `backend/scout/stale_listings.py` | 124 | `backend/scout/` | Agent-vs-owner targeting; avoids tortious interference |
| `backend/scout/ingest.py` | 117 | `backend/scout/` | |
| `backend/scout/convert.py` | 60 | `backend/scout/` | |
| `backend/scout/reddit.py` | 137 | `backend/scout/` | Trunk has no Reddit source |
| `backend/voice/voicemail.py` | 109 | `backend/voice/` | AMD handling; trunk has none |
| `backend/voice/post_call_intel.py` | 116 | `backend/voice/` | |
| `backend/alerts/owner.py` | 79 | `backend/alerts/` | Owner escalation |
| `backend/alerts/followup.py` | 133 | `backend/alerts/` | Fires without needing `end_call` |
| `backend/dispo/blast.py` | 106 | `backend/dispo/` | |
| `backend/dispo/matcher.py` | 62 | `backend/dispo/` | |
| `bob/prioritizer.py` | 108 | `backend/bob/` | Waiting-on-human as a **tier**, not a bonus |
| `bob/worker.py` | 159 | `backend/bob/` | Correct memory field mapping |
| `dialer/` (4 files) | 98 | `dialer/` | Trunk has no dialer worker |
| `discovery/` (3 files) | 83 | `discovery/` | Trunk has no discovery worker |
| `backend/api/routes/intake.py` | 84 | `backend/api/routes/` | Public intake endpoint |
| `backend/api/routes/dispo.py` | 73 | `backend/api/routes/` | |
| `backend/api/routes/workers.py` | 83 | `backend/api/routes/` | Worker health |
| `backend/api/routes/discovery.py` | 48 | `backend/api/routes/` | |
| `backend/api/routes/comps.py` | 44 | `backend/api/routes/` | |
| `backend/comps/service.py` | 24 | `backend/comps/` | |
| `dashboard/app/(dashboard)/health/`, `reasoning/`, `discovered/`, `buyers/` | — | `dashboard/app/` | Trunk has no equivalent pages |
| `dashboard/components/` (9) | — | `dashboard/components/` | Trunk has 1 component total |
| `dashboard/middleware.ts`, `lib/supabase/{client,server}.ts` | — | `dashboard/` | Auth the trunk dashboard lacks |
| `dashboard/app/sell/page.tsx` + `app/api/lead/route.ts` | — | `dashboard/app/` | Public form; secret stays server-side |
| `tests/` — 24 of 41 files | — | `tests/` | The tests for everything above |
| `supabase/migrations/0004`–`0010` | — | `supabase/migrations/` | Renumbered; voicemail, dispo, stale listings, worker_runs, seller_facts, data_quality, call_priority |
| `PROJECT.md` | 657 | repo root | The end-to-end reference. **§18 bug history must survive the merge** |
| `docs/LEAD_SOURCES.md` | — | `docs/` | |

### 5.2 `ADAPT` — merge into the trunk's larger version, do not replace it

| File | Lines | vs trunk | Merge decision |
|---|---|---|---|
| `backend/voice/context.py` | 202 | trunk 59 | Take Sophia-Agent's `build_caller_awareness_str`, `build_call_brief_str`, unknown-caller creation. **This is the one file where the donor is bigger** |
| `backend/voice/tools.py` | 242 | trunk 864 | Take only the `mark_call_ended` fix that stops DEAD from resetting `opted_out` |
| `backend/scout/scorer.py` | 285 | trunk 316 | Diff scoring bands |
| `backend/scout/parser.py` | 186 | trunk 185 | Near-identical; pick one, delete the other |
| `backend/comps/calculator.py` | 137 | trunk 132 | Diff MAO/ARV rounding |
| `backend/alerts/sms.py` | 89 | trunk 140 | Take the hours + DNC gate |
| `backend/alerts/email.py` | 67 | trunk 309 | Take `send_raw_email` if absent |
| `backend/lib/db.py` | 831 | trunk 1268 | Take intake/validation/voicemail/dispo accessors only |
| `AGENTS.md` | — | — | Merge the config.py and DB-access rules into the trunk's |

### 5.3 `LEGACY` — frozen, superseded by the trunk

`backend/voice/agent.py` (240 vs 1129), `webhook.py` (169 vs 418),
`outbound.py` (53 vs 411), `api/main.py` (51 vs 254), and routes
`calls.py`, `leads.py`, `properties.py`, `offers.py`, `health.py`.

The repo stays deployed and frozen as the fallback until Gate 10 opens. Nothing
in it is developed further.

---

## 6. `bob-intelligence-` — 21 files, `LEGACY` as a repo

No consumer. No unique capability. Its `backend/worker/loop.py` (128 lines) and
`backend/db/client.py` (59) are superseded by the trunk.

**Archive the repo after §8.1 harvests the module bodies that win.** Not before —
`brief_generator.py` at 141 lines is the longest of the three and may carry logic
the others dropped.

| File | Lines | Tag |
|---|---|---|
| `backend/call_planner/*` (5) | 313 | `ADAPT` → harvest per §8.1, then archive |
| `backend/contracts/call_brief.py` | 60 | `ADAPT` → diff against trunk's 44 |
| `backend/worker/loop.py` | 128 | `LEGACY` |
| `backend/db/client.py` | 59 | `LEGACY` |
| `backend/events/bob_events.py` | 61 | `LEGACY` |
| `backend/decisions/decision_logger.py` | 30 | `LEGACY` |
| `backend/config.py`, `main.py`, `__init__.py` × 6 | 18 | `LEGACY` |

---

## 7. `The-Dashboard` (Karpathys) — authority, stays separate

Classified by module. ~670 files, 28 test files, phase 15 of 16 with
"Hardening" never started — so `HARDEN` here means *first* test, not retest.

| Module | Files | Tag | Obligation |
|---|---|---|---|
| `backend/governance/` | 18 | `HARDEN` | Fail-closed proven under test. Currently the largest untested surface in the system |
| `backend/approvals/` | 5 | `HARDEN` | Atomic approval; race and expiry tests |
| `backend/events/` | 6 | `KEEP` + `HARDEN` | Has `idempotency.py`, `replay.py`, `store.py` — the outbox the trunk needs. Ordering must be proven |
| `backend/security/` | 5 | `HARDEN` | auth, rbac, permissions, rate_limits, secrets — all unverified |
| `backend/models/` | 47 | `KEEP` | Includes `ai_decision`, `ai_execution`, `approval`, `audit_log`, `domain_event`, `context_snapshot` |
| `backend/repositories/` | 21 | `KEEP` | |
| `backend/api/routes/ingest.py` | 1 | `HARDEN` | Fails open on unset secret (3.5) |
| `backend/api/routes/sophia_bridge.py` | 1 | `HARDEN` | The Bob↔Sophia seam; contract unverified `[UNVERIFIED]` |
| `backend/api/routes/` — other 26 | 26 | `HARDEN` | Authorization unverified |
| `backend/sophia/` | 16 | `ADAPT` | See §8.2 — keep the governance-bearing half |
| `backend/calls/` + `calls/runtime/` | 11 | `ADAPT` | Overlaps trunk `voice/states/` |
| `backend/context/` (+ adapters) | 21 | `KEEP` | |
| `backend/workflows/` | 25 | `ADAPT` | Overlaps trunk `workflows/engine.py` — one workflow engine survives |
| `backend/transcripts/` (+ sub) | 25 | `ADAPT` | Overlaps trunk `qa/transcript_intel.py` |
| `backend/research/` | 12 | `KEEP` | |
| `backend/ai/` | 16 | `KEEP` | |
| `backend/leads/`, `properties/` | 8 | `ADAPT` | Lead truth must live in exactly one place (§17.1) |
| `backend/realtime/`, `observability/`, `middleware/`, `core/`, `db/`, `config/`, `schemas/`, `services/`, `integrations/`, `workers/`, `scripts/` | ~40 | `KEEP` | |
| `backend/tests/` + `tests/` | 58 | `HARDEN` | 28 test files against ~670 source files |
| `frontend/`, `realtime/`, `vision/`, `memory/`, `sophia/` | — | `[UNVERIFIED]` | Not surveyed. **Must be enumerated before the checklist below is final** |
| `REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md` | 1 | `DELETE` | Superseded by the copy now in the trunk |

---

## 8. Resolving the duplicates

### 8.1 Bob's call planner — three copies, resolved per module

All three copies were diffed. The result is not what repo size predicts.

| Module | Trunk | Sophia-Agent | bob-intelligence- | **Winner** | Evidence |
|---|---|---|---|---|---|
| `brief_generator.py` | 58 | 136 | 141 | **Sophia-Agent** | Trunk has **one** function. The other two have `_derive_phase`, `_derive_mood`, `_derive_confidence`. Sophia-Agent's ≡ bob-intelligence-'s plus `stale_listing` and `expired_listing` distress types |
| `avoidances_builder.py` | 33 | 63 | 52 | **Sophia-Agent** | Longest; superset |
| `escalation_rules.py` | 30 | 47 | 51 | **diff required** | bob-intelligence- is longest — check whether it holds rules the others dropped |
| `checkbox_selector.py` | 40 | 39 | 42 | **diff required** | Within 3 lines; the ladder-order fix must survive |
| `objective_selector.py` | 30 | 27 | 27 | **diff required** | Sophia-Agent ≡ bob-intelligence-; trunk diverges |

**The trunk loses this directory.** `backend/bob/call_planner/brief_generator.py`
is a stub against the other two — one function where they have four. Shipping
the trunk as-is would ship a Bob that cannot derive phase, mood, or confidence.

This is the concrete case for §2's rule: **bigger repo, worse module.**

Resolution procedure, per module:
1. Three-way diff.
2. Record the winning body and one sentence of why, in this file.
3. Land the winner in `backend/bob/call_planner/` with its tests.
4. Delete the other two copies **in the same commit**.

### 8.2 Sophia's runtime — two halves, not two copies

`The-Dashboard/backend/sophia/` (16 files) is **not** a third voice pipeline. It
is a session/turn state machine with governance attached — `turn.py` imports
`GovernanceEngine` and has an `awaiting_approval` state, which is precisely the
§14 authority the trunk's `voice/` lacks.

The two are complementary. The split:

| Concern | Owner | Loser |
|---|---|---|
| Speech, VAD, turn-taking, prosody, processors | **Trunk `voice/`** | — |
| Session/turn lifecycle, approval gating, replay, shadow logging, warm-transfer context packet | **Karpathys `sophia/`** | — |
| `contracts` | **Karpathys** (`sophia/contracts.py`, 274 lines, frozen dataclasses) | Trunk emits into them |
| `interruption` | **Trunk** (`processors/interruption.py` — real audio) | Karpathys `sophia/interruption.py` records it |
| Trust / confidence / deal-heat | **diff required** | Trunk `trust_tracker.py` + `deal_heat_scorer.py` vs Karpathys `sophia/metrics.py` + `confidence_engine.py`. **Exactly one computes; the other reads** |
| `tools` | **Trunk** (`voice/tools.py`) | Karpathys `sophia/tools.py` gates them |

The one thing that must not happen: both sides computing trust independently and
disagreeing. That is failure mode #1 wearing a new hat.

---

## 9. The checklist

`0/150`. Item numbers are **execution** order. Where that differs from the
spec's gate order, the spec gate is named in the heading. Nothing in a gate
starts before the previous gate's tests pass.

### Gate 2 — finish the map itself · `0/6`

- [ ] 1. Enumerate `The-Dashboard/{frontend,realtime,vision,memory,sophia}` — currently `[UNVERIFIED]`, and the only unclassified surface left
- [ ] 2. Determine which ingest endpoint is deployed (3.4) — Next.js route or FastAPI service
- [ ] 3. Three-way diff `escalation_rules.py`; record winner
- [ ] 4. Three-way diff `checkbox_selector.py`; record winner
- [ ] 5. Three-way diff `objective_selector.py`; record winner
- [ ] 6. Ratify the §18 `[OPEN]` items, or confirm the §0 assumptions stand

### Gate 2.5 — seven fixes for the six live defects, before anything is built on top · `0/7`

These are not rebuild work. They are bugs in running code.

- [ ] 7. `_check_dnc` fails closed (3.1) — **highest priority in this document**
- [ ] 8. Recipient-timezone calling hours replace hardcoded Pacific (3.2), all 6 call sites
- [ ] 9. Authenticate the dashboard ingest routes, or delete them (3.3)
- [ ] 10. `The-Dashboard` ingest denies on unset secret (3.5)
- [ ] 11. `backend/lib/config.py` lands; startup fails loudly on missing required vars (3.6)
- [ ] 12. `.env.example` populated — it is currently a 0-byte file against 32 env-reading modules
- [ ] 13. `test_env_example.py` moved over so 12 cannot silently rot

### Gate 3 — Karpathys hardened · `0/8`

- [ ] 14. Governance fail-closed proven under test
- [ ] 15. Actor integrity — every event carries an authenticated actor
- [ ] 16. Approval atomicity — race and expiry tests
- [ ] 17. Webhook authentication across all 28 routes
- [ ] 18. Event ordering guarantees tested
- [ ] 19. Resource scoping / RBAC tested
- [ ] 20. `sophia_bridge.py` contract verified against the trunk
- [ ] 21. Rate limits tested

### Gate 4 — shared infrastructure · `0/9`

- [ ] 22. Transactional outbox (reuse `The-Dashboard/backend/events/`)
- [ ] 23. `karpathys/emitter.py` rewritten as an outbox writer — no more silent loss
- [ ] 24. §5 event envelope: actor, causation, idempotency key, version
- [ ] 25. Execution ledger — no consequential action without a row
- [ ] 26. Contact + append-only permission ledger
- [ ] 27. `may_contact()`, failing closed
- [ ] 28. CommunicationAttempt
- [ ] 29. Appointment
- [ ] 30. MemoryFacts with per-fact provenance

### Gate 5 *(spec G5 — Sophia V2)* — merge the donor · `0/38`

The 36 `MOVE` rows in §5.1, each arriving with its tests, plus:

- [ ] 31–66. `MOVE` each §5.1 item (36 items)
- [ ] 67. Renumber Sophia-Agent migrations `0004`–`0010` into the trunk sequence
- [ ] 68. Full suite green: 257 + 426 tests, no import-path breakage

### Gate 6 *(spec G7 — Bob V2)* — resolve the duplicates · `0/17`

Run ahead of spec G6: resolving triplication before wiring means wiring one Bob,
not three.

- [ ] 69–73. Land the 5 winning `call_planner` modules (§8.1)
- [ ] 74. Delete `Sophia-Agent/bob/` planner copies
- [ ] 75. Archive `bob-intelligence-`
- [ ] 76–84. The 9 §5.2 `ADAPT` merges, decision recorded per file
- [ ] 85. Resolve the trust/confidence ownership question (§8.2) — exactly one computes

### Gate 7 *(spec G6 — Sophia wired)* — route every side effect through the Orchestrator · `0/16`

- [ ] 86–94. The 9 `backend/alerts/` modules call `may_contact()` before sending
- [ ] 95. `voice/outbound.py` + `outbound_webhook.py` gated
- [ ] 96. `ringless.py` hard-gated behind explicit enable + consent
- [ ] 97. Zero direct external side effects outside the Orchestrator, proven by test
- [ ] 98. Zero independent CRM writes from the voice path
- [ ] 99. `voice/memory.py` becomes a MemoryFact reader
- [ ] 100. `workflows/engine.py` consults governance
- [ ] 101. One workflow engine survives (trunk vs Karpathys `workflows/`)

### Gate 8 *(spec G8)* — contracts and staleness · `0/9`

- [ ] 102. `CallBrief` → `StrategyPlan`: `plan_id`, `issued_at`, `expires_at`, `confidence`
- [ ] 103. `IntelPacket` carries provenance per fact
- [ ] 104. `call_brief_loader.py` rejects expired plans
- [ ] 105. Strategy snapshots
- [ ] 106. Automatic invalidation on new facts
- [ ] 107. Stale-plan execution proven impossible
- [ ] 108. Valuations always ranges (§17.10)
- [ ] 109. Offer-authority gate in `voice/tools.py` (§10.1)
- [ ] 110. Deterministic STOP enforced outside the model (§17.12)

### Refactor *(no gate)* — split the big files · `0/5`

Deferred deliberately: these are refactors, and refactoring before the seams
are proven just moves the bugs.

- [ ] 111. `lib/db.py` (1268) split by aggregate
- [ ] 112. `voice/agent.py` (1129) split
- [ ] 113. `voice/tools.py` (864) split
- [ ] 114. `processors/context_tracker.py` (640) split
- [ ] 115. `alerts/drip.py` (485) split

### Gate 9 *(spec G9)* — learning layer · `0/6`

- [ ] 116. Replay proven faithful
- [ ] 117. Grading versioned
- [ ] 118. Shadow mode running
- [ ] 119. Evals proven out of the decision path (§17.15)
- [ ] 120. Process mining over the execution ledger
- [ ] 121. Simulator wired to the eval harness

### Gate 10 *(spec G10)* — controlled real calls · `0/8`

- [ ] 122. FCC AI-disclosure unconditional in `processors/ai_identity.py`
- [ ] 123. Internal calls
- [ ] 124. Known testers
- [ ] 125. Adversarial testers
- [ ] 126. Shadow mode against live inbound
- [ ] 127. Canary outbound with per-call human approval
- [ ] 128. Graduated caps
- [ ] 129. `Sophia-Agent` fallback retired

### Cleanup · `0/21`

- [ ] 130. Delete `scout/deduper.py` (0 bytes)
- [ ] 131. Delete `voice/prompts/sophia_legacy_runtime.md`
- [ ] 132. Delete `The-Dashboard/REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md`
- [ ] 133–148. Reconcile the 16 `SOPHIA_*.md` behaviour specs against §12
- [ ] 149. `AGENTS.md` gains the config.py, no-shared-DB, and fail-closed rules
- [ ] 150. `Procfile` / `railway.json` gain the dialer and discovery workers

---

## 10. Order of operations

**Gate 2.5 is not optional and does not wait.** Items 7–13 are seven bugs in
code that is deployed. `_check_dnc` failing open and calling hours assuming
Pacific are legal exposure, not technical debt, and neither depends on any
architectural decision in the V2 spec. They can be fixed this week regardless of
what you decide about monorepos.

**Everything else waits on ratification.** Every `MOVE` arrow in §5 reverses if
you name a different trunk. Do not start Gate 5.

### What this map deliberately does not do

- **It does not schedule.** 150 items with no dates. One operator, unknown
  hours — any estimate I gave you would be invented.
- **It does not touch `The-Dashboard`'s frontend.** Unenumerated, marked
  `[UNVERIFIED]`, item 1.
- **It does not promise the merge is worth it.** Same honest note as §19 of the
  spec: Sophia V1 works, is tested, and has still never placed a live call.
  Gate 2.5 makes the live system legally safer in about a week. Gates 3–11 make
  it durable over months. If the goal is revenue this quarter, do Gate 2.5, then
  place a real call, then come back and read this document with what you learn.
