# REI Agent — Master Reference

Everything about this project in one place: what it is for, what exists, how it
works, what is broken, and what the plan is.

**Written 2026-09-11.** Every number here was measured off the repositories, not
recalled. Claims I could not verify are marked `[UNVERIFIED]`.

---

## 0. Read this first

### The five documents

| Document | Answers | Status |
|---|---|---|
| **`MASTER_REFERENCE.md`** (this) | What is this, what exists, what is broken | Current |
| **`REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md`** | What the system *should* be | Proposed, unratified |
| **`REBUILD_MAP.md`** | Which file goes where, in what order | Proposed, depends on the above |
| **`AUDIT_AND_GRADE.md`** | Brutal grade, all 30 defects, regulatory research, what to do next | Current |
| **`Sophia-Agent/PROJECT.md`** | How the V1 system works end to end | Accurate for V1 only |

Plus `AGENTS.md` (hard rules) and 16 `SOPHIA_*.md` behaviour specs.

### The one-paragraph version

An autonomous real-estate acquisition system for San Joaquin County, California.
It finds distressed properties, prices them, calls the owners with an AI voice
agent, qualifies them, and books walkthroughs. Roughly 20,000 lines of Python
across four repositories, four years of architecture documents, **and it has
never placed a live call.** The code is substantial and the plan is sound. The
gap between them is the entire problem.

### The single most important thing to know

> There are **four** repositories and they duplicate each other. Bob's call
> planner exists in three copies that have all diverged from one another.
> Sophia's runtime exists in three. Two different services answer the same
> ingest URL. Nothing downstream can be trusted until that is resolved.

---

## 1. The business

| | |
|---|---|
| **Owner** | Angelo Washington, operating as Alanzo Alcarez |
| **Business** | San Joaquin House Buyers |
| **Market** | San Joaquin County, CA — Stockton, Lodi, Manteca, Tracy, Ripon |
| **Model** | Wholesaling — contract distressed property, assign to a cash buyer |
| **Phone** | +1 209 881 4144 (SignalWire) |
| **Domain** | sanjoaquinhousebuyers.com |
| **Operator count** | One |

### What the system is supposed to do

1. Find property owners likely to sell below market, before they list.
2. Price the property well enough to make a defensible offer.
3. Reach the owner and hold a real conversation.
4. Qualify: motivation, timeline, condition, price expectation.
5. Book a walkthrough, or schedule an intelligent follow-up.
6. Escalate to the human when it matters.
7. Never contact anyone it is not legally allowed to contact.

### What "working" means

Not "the code runs." Working means: **a real seller answers the phone, has a
conversation they do not resent, and a walkthrough lands on the calendar** —
with a record of who authorized every step.

By that definition the system has not worked yet, because step one has never
been attempted with a real person.

---

## 2. The four repositories

| Repo | Role | Size | Last commit | Tests |
|---|---|---|---|---|
| **`REI-AGENT`** | The trunk — Bob + Sophia + orchestration | 137 py files, 19,787 LOC, 249 tracked | 2026-06-08 | 226 collected, **suite red** (§9) |
| **`The-Dashboard`** | Karpathys — authority, governance, audit | ~670 files | 2026-05-30 | 28 test files |
| **`Sophia-Agent`** | V1 — the donor, and the fallback | ~5,900 LOC, 174 tracked | 2026-06 | 426 tests |
| **`bob-intelligence-`** | Standalone Bob — superseded | 21 files | 2026-06-08 | none |

### Which one is "the system"?

`REI-AGENT`. It is the newest, the largest, the only one where Bob and Sophia
are actually integrated, and it holds the typed contracts the V2 spec builds on.

But it is **not** the best code everywhere. `Sophia-Agent` has the compliance
engine, the canonical intake path, data validation, voicemail, dispo,
heartbeats — and 426 tests to `REI-AGENT`'s 226. The rebuild map (§12) merges
the donor into the trunk rather than picking a winner outright.

---

## 3. Architecture — the intended model

```
KARPATHYS   authority + governance + audit + memory + execution ledger
   │        "what is true, and what is allowed"
   │
BOB         acquisition intelligence + underwriting + strategy
   │        "what business move makes sense"
   │
SOPHIA      realtime conversation + turn-taking + seller state + speech
   │        "how to conduct this conversation"
   │
ORCHESTRATOR  who gets contacted, when, how, and whether it is permitted
   │
EVALUATION    replay + grading + simulation — advisory, never in the decision path
```

### The rule everything derives from

> **Karpathys knows what is true and what is allowed.**
> **Bob decides what business strategy makes sense.**
> **Sophia decides how to conduct the conversation.**
> **Humans retain authority over consequential decisions.**

### The three failure modes it exists to prevent

1. **Duplicate truth** — two systems each owning a fact, silently disagreeing.
2. **Unsafe autonomy** — an AI acting with no human authorization and no ledger row.
3. **Invisible drift** — behaviour changing with no record of when, why, or on whose authority.

**All three are currently live.** See §9.

---

## 4. How a lead becomes a deal

```
DISCOVERY    scrapers + CSV import + inbound + web form
   ↓
SCORING      distress score 0–100
   ↓
VALIDATION   phone / name / address / property sanity   [Sophia-Agent only]
   ↓
SKIP TRACE   BatchData → phone numbers                  [Sophia-Agent only]
   ↓
PRICING      comps → ARV → MAO
   ↓
BOB          prioritize the queue, write the call brief
   ↓
COMPLIANCE   calling hours · DNC · opt-out · consent
   ↓
SOPHIA       the call
   ↓
OUTCOME      HOT / WARM / COLD / DEAD → workflow state
   ↓
FOLLOW-UP    SMS / email / voicemail / drip / re-call
   ↓
DISPOSITION  match to cash buyers, blast the deal
```

### Lead stages (`leads.stage`)

`new` → `contacted` → `offer_made` → `walkthrough_booked` → `under_contract` → `closed`, plus `dead`.

### Workflow states (`backend/workflows/engine.py`)

`new_lead`, `active_contact`, `followup_required`, `appointment_pending`,
`appointment_confirmed`, `negotiation`, `under_review`, `dead_lead`, `closed`.

Disposition maps: `HOT → appointment_pending`, `WARM/COLD → followup_required`,
`DEAD → dead_lead`.

---

## 5. Lead sources

All in `backend/scout/` unless noted.

| Source | File | Signal |
|---|---|---|
| Propwire CSV | `parser.py` | Bulk distressed export — the primary volume source |
| Tax delinquency | `tax_scraper.py` | Years behind, amount owed |
| Court records | `court_scraper.py` | Probate, divorce, judgments |
| Eviction filings | `eviction_scraper.py` | Tired landlord — **see §9.11, legal question open** |
| Expired listings | `expired.py` | Listed and failed to sell |
| CRMLS | `crmls_scraper.py` | Licensed MLS feed |
| Cash buyers | `cash_buyer_scraper.py` | Builds the dispo buyer list, not seller leads |
| Social | `social_scraper.py` | |
| RSS | `rss_scraper.py` | |
| Reddit | `Sophia-Agent/backend/scout/reddit.py` | **Not in the trunk yet** |
| Stale listings | `Sophia-Agent/backend/scout/stale_listings.py` | 65+ days on market. **Not in the trunk yet** |
| Inbound call / SMS | `backend/voice/`, `backend/api/routes/sms.py` | |
| Web form | `Sophia-Agent/dashboard/app/sell` | **Not in the trunk yet** |

### The canonical intake path does not exist in the trunk

`Sophia-Agent/backend/scout/intake.py` is the one function every lead source is
supposed to funnel through — it normalizes phones to `+1XXXXXXXXXX`, checks six
phone formats for duplicates, and assigns a source-default score. The trunk has
no equivalent, so **each scraper writes leads its own way.** That is
`REBUILD_MAP` item 31–66 and it is the highest-value single move in the merge.

---

## 6. Scoring and pricing

### Distress score — `backend/scout/scorer.py`

0–100, higher is more urgent. Thresholds:

| Threshold | Value | Effect |
|---|---|---|
| `SCORE_HIGH_PRIORITY` | 85 | Alert the owner, call first |
| `SCORE_CREATE_LEAD` | 50 | Becomes a lead |
| `SCORE_DRIP_ONLY` | 35 | Drip campaign only, no call |

Weights (additive, then clamped):

| Signal | Points |
|---|---|
| Notice of trustee sale filed | +65 |
| Pre-foreclosure | +55 |
| Notice of default (without pre-FC) | +55 |
| Tax delinquent 3+ years | +45 |
| Vacant | +42 |
| Tax delinquent 1–2 years | +30 |
| Out-of-state mailing address | +30 |
| Lien > $5,000 | +25 |
| Absentee owner | +22 |
| Code violation | +18 |
| Free and clear | +15 |
| Owned 20+ / 15 / 10 / 7 / 5 / 2 yrs | +20 / 16 / 12 / 8 / 5 / 2 |
| Price reduced | +15 |

Combination bonuses: vacant + pre-FC `+28`, vacant + absentee `+22`,
pre-FC + equity ≥50% `+22`, absentee + tax-delinquent `+20`,
tax-delinquent + free-and-clear `+20`, vacant + free-and-clear `+18`.

### The money math — `backend/comps/calculator.py`

```
MAO = (ARV × MAO_MULTIPLIER) − MAO_REPAIR_BUFFER
```

| Constant | Default | Env var |
|---|---|---|
| `MAO_MULTIPLIER` | 0.70 | `MAO_MULTIPLIER` |
| `MAO_REPAIR_BUFFER` | $25,000 | `MAO_REPAIR_BUFFER` |

**All money is integer cents.** The buffer is stored in dollars and multiplied
by 100 at use. `max(..., 0)` floors MAO at zero.

> ⚠️ This rule is violated in `backend/lib/intel_assembler.py` and the bug is
> live. See §9.9.

---

## 7. Sophia — the voice agent

### Who she is

Sophia Reyes, 25, Stockton native, acquisitions coordinator. Lincoln High, two
years at Delta College, uncle flipped houses in Fresno. Lives in Brookside,
drives a CR-V. Eighteen months with Alanzo. California-casual speech —
`like`, `yeah`, `totally`, `honestly`, uptalk when inviting a response, reacts
before responding, never corporate.

The persona is not decoration. A wholesaling call that sounds like a script gets
hung up on, and the entire system's value depends on the first fifteen seconds.

### The pipeline — `backend/voice/agent.py` (1,129 lines)

```
transport.input()        SignalWire mulaw 8kHz → resampled 16kHz PCM
stt                      Deepgram nova-2
stt_mute_proc            mutes STT upstream while the bot speaks
interruption_proc        InterruptionFrame → spoken acknowledgement
ai_identity_proc         "are you a bot?" → forced disclosure (FCC)
context_tracker          extracts signals, injects context, compresses at turn 6
backchannel_proc         "Mhm" / "Yeah" after 4s of seller speech
context_aggregator.user  accumulates transcription → LLMContextFrame on VAD stop
llm                      Anthropic (Groq fallback)
sentence_streamer        buffers tokens → flushes on sentence/comma boundary
fair_housing_filter      strips demographic / steering language
tts                      ElevenLabs (Together AI Orpheus fallback)
latency_proc_tts         measures UserStopped → STT → TTS_start → TTS_audio
transport_output         mulaw back to SignalWire
context_aggregator.asst  accumulates assistant turns
```

### Turn-taking

```python
SileroVADAnalyzer(confidence=0.7, start_secs=0.2, stop_secs=0.5, min_volume=0.6)
```

`stop_secs=0.5` is better than Pipecat's 0.2 default, which cuts sellers off
mid-sentence. `Sophia-Agent` uses 0.6 **plus** `LocalSmartTurnAnalyzerV3`, which
decides turn-end from semantics rather than silence alone.

> The trunk does **not** use smart turn detection, even though
> `livekit-agents[turn-detector]` is in `requirements.txt`. A dependency is
> installed for a feature that is not wired.

### Her cognition modules

| Module | Lines | Does |
|---|---|---|
| `processors/context_tracker.py` | 640 | Signal extraction, context injection, compression |
| `seller_profile_engine.py` | 173 | Who am I talking to |
| `resistance_tracker.py` | 172 | Pushback intensity |
| `deal_heat_scorer.py` | 172 | How live is this |
| `objective_engine.py` | 133 | What am I trying to get |
| `microstate_engine.py` | 124 | Fine-grained conversational state |
| `emotional_state_engine.py` | 123 | Seller affect |
| `momentum_tracker.py` | 112 | Is this going anywhere |
| `trust_tracker.py` | 103 | Rapport |
| `fatigue_detector.py` | 86 | Are they done talking |
| `turn_controller.py` | 76 | Turn arbitration |

Plus `geo_phrases.py` (216 lines of Stockton-specific local references),
`speech_chunker.py`, `silence_handler.py`, `prompt_budget.py`.

### Her tools — `backend/voice/tools.py` (864 lines)

Offer range, appointment booking, callback request, send details, end call.

> No offer-authority gate exists. The V2 spec says Sophia makes **no binding
> offer** in V2 (§10.1). Nothing in the code enforces that yet.

### Conversation states

Documented in `docs/runtime/CALL_STATES.md` as living in
`backend/voice/flows.py` with turn budgets — `warm_open` 2, `discovery` 6,
`price_discussion` 4, `objection_handling` 4, `close` 4, `end_call` 2.

> **`backend/voice/flows.py` does not exist.** The doc describes a module that
> is not in the repository. See §9.10.

---

## 8. Bob — the call planner

Bob decides *what the call is for* before Sophia decides *how to say it*.

### The checkbox ladder

Each call targets exactly one missing fact, in order:

`identity` → `motivation` → `timeline` → `condition` → `occupancy` → `next_step`

`checkbox_selector.py` picks the lowest unsatisfied rung. One objective per call
beats a checklist the seller experiences as an interrogation.

### The brief — `backend/contracts/call_brief.py`

```python
CallBrief:
    phase:       VERIFY | LIGHT_DISCOVERY | QUALIFY | NEXT_STEP | WRAP
    objective:   str
    missing_box: condition | timeline | motivation | next_step |
                 identity | occupancy | none
    mood:        guarded | open | skeptical | distressed | motivated | unknown
    avoid:       list[str]
    escalation:  list[str]
    opener_hint: str | None
```

This is the best-designed thing in the codebase — a closed-enum typed contract
with explicit serialization. The V2 `StrategyPlan` extends it with `plan_id`,
`issued_at`, `expires_at`, and `confidence` so a stale plan cannot be executed.

### The prioritizer

`Sophia-Agent/bob/prioritizer.py` ranks the call queue. Its key design decision:
**"waiting on a human" is a tier, not a bonus.** A seller who asked for a
callback sorts above every cold 90-distress lead, because a scoring bonus loses
to a high enough distress score and a tier never does.

> Not in the trunk yet. `REBUILD_MAP` §5.1.

### Bob is triplicated

| Module | Trunk | Sophia-Agent | bob-intelligence- | Winner |
|---|---|---|---|---|
| `brief_generator.py` | 58 | 136 | 141 | **Sophia-Agent** |
| `avoidances_builder.py` | 33 | 63 | 52 | **Sophia-Agent** |
| `escalation_rules.py` | 30 | 47 | 51 | diff required |
| `checkbox_selector.py` | 40 | 39 | 42 | diff required |
| `objective_selector.py` | 30 | 27 | 27 | diff required |

The trunk's `brief_generator.py` has **one** function. The other two have four —
`_derive_phase`, `_derive_mood`, `_derive_confidence`, and the generator. The
trunk's Bob cannot derive phase, mood, or confidence at all.

**The biggest repo has the worst Bob.** That is why the rebuild map resolves
this per module rather than per repo.

---

## 9. The defect register

Fifteen defects, found by reading the code rather than from a bug tracker. Each
is reproducible from the file and line given. Ordered by consequence.

### 9.1 `_check_dnc` fails open — legal exposure

`backend/compliance/compliance.py:26-33`

```python
except Exception as e:
    logger.warning("dnc_check failed phone={} error={}", phone, str(e))
    return False          # ← "not on the DNC list" → "go ahead and call"
```

Any database hiccup becomes a call to a Do-Not-Call number. `Sophia-Agent`'s
equivalent fails closed. **Fix this before anything else in this document.**

### 9.2 Calling hours assume every seller is in Pacific — legal exposure

`compliance.py:17-23` hardcodes `America/Los_Angeles`, permitting hours
9 through 21. Four more sites hardcode the same zone: `voice/outbound.py:17`,
`voice/tools.py:16`, `voice/appointment_scheduler.py:13`, `alerts/sms.py:5`, and
the APScheduler instance in `api/main.py:140`.

`CALLING_HOURS_END=21` Pacific is **midnight Eastern**. TCPA's window is 8am–9pm
**in the called party's** timezone. `Sophia-Agent/backend/compliance/timezones.py`
maps area code → IANA zone with a strict two-zone fallback for unknown codes.

### 9.3 Dashboard ingest routes have no authentication

`dashboard/app/api/ingest/{call,turn,ended,complete}/route.ts` write directly
into Supabase `call_events`. Grepped across all four repos for any secret,
header, or auth check on these routes: **none exists.** Anyone who can reach the
deployed URL can inject fabricated call events into the system of record.

`backend/karpathys/client.py:23` faithfully sends `X-Karpathys-Secret` — to an
endpoint that ignores it.

### 9.4 Two different services answer the same ingest path

`KARPATHYS_URL/api/v1/ingest/*` resolves to **either**:

- `The-Dashboard/backend/api/routes/ingest.py` — real service, checks the
  secret, dedupes on `provider_call_id`; **or**
- `REI-AGENT/dashboard/app/api/ingest/*/route.ts` — no auth, no dedupe, writes
  to the same Supabase the backend uses.

Which one is live depends on an environment variable. The second violates the
"no shared database" rule outright. `[UNVERIFIED]` — I cannot read deployed env
from here, and this must be settled before Gate 3 hardens the wrong one.

### 9.5 Karpathys ingest also fails open

`The-Dashboard/backend/api/routes/ingest.py:21`

```python
if _WEBHOOK_SECRET and x_karpathys_secret != _WEBHOOK_SECRET:
```

Unset `KARPATHYS_WEBHOOK_SECRET` and the condition short-circuits — every
request is accepted. A missing environment variable silently disables
authentication.

### 9.6 No config layer, and `.env.example` is empty

The trunk has no `backend/lib/config.py`. **32 backend files read `os.environ`
directly**, seven of them with `os.environ[...]` which raises at import time.
`.env.example` is a **0-byte file**. Nothing can tell you at startup that a
required variable is missing — which is precisely how 9.5 stays invisible.

`Sophia-Agent/backend/lib/config.py` exists and is enforced by
`test_env_example.py`.

### 9.7 Events to Karpathys are lost silently

`backend/karpathys/emitter.py` wraps all nine emit functions in `try/except` +
log. Karpathys down, slow, or misconfigured → the call proceeds and the event is
**gone**. Two immediate retries, no outbox, no dead-letter queue, and nothing on
either side that would notice.

This is failure mode #3 with the mechanism already installed.

### 9.8 `DEAD` disposition conflates "unresponsive" with "revoked consent"

`backend/lib/db.py:362-367`

```python
elif disposition == "DEAD":
    client.table("leads").update({
        "opted_out": True,
        ...
```

`DEAD` covers wrong number, no answer, and not interested. `opted_out` means the
person exercised a legal right to revoke consent. Setting the second from the
first is conservative on TCPA — it will not cause an illegal call — but it
permanently destroys re-marketable leads and corrupts the consent record. Once
the append-only permission ledger exists (V2 §7), you can no longer distinguish
"said STOP" from "didn't pick up."

### 9.9 Money unit confusion makes a governance flag always fire

`backend/lib/intel_assembler.py`

```python
arv = arv_cents // 100          # line 87  → converts cents to DOLLARS
...
conflict_flags = _detect_conflicts(comp_arv=arv, ...)   # line 115

spread = comp_arv - seller_price_floor
if spread < 3000000:            # line 29  → compares against CENTS
    flags.append({"type": "SPREAD_TOO_THIN", ...})
```

A genuine $420,000 ARV arrives as `420000` dollars and is measured against a
$30,000 threshold expressed as `3000000` cents. **`SPREAD_TOO_THIN` fires on
essentially every deal.** A flag that is always on is a flag nobody reads.

Violates the `AGENTS.md` rule "all money values stored as integer cents." The
test fixtures in `tests/test_intel_governance.py` pass dollars too, so two of
those tests pass for the wrong reason and a third fails.

### 9.10 Tests and docs reference three modules that do not exist

| Referenced | By | Exists |
|---|---|---|
| `backend.voice.processors.spoken_renderer` | `test_batch3_regression.py`, `test_batch4_regression.py` | **No** |
| `backend.voice.processors.emotion` | 4 tests | **No** |
| `backend/voice/flows.py` | `docs/runtime/CALL_STATES.md` | **No** |

`EmotionDetectorProcessor` is also listed in `docs/runtime/PIPELINE_ORDER.md` as
an active pipeline stage.

### 9.11 Eviction scraper — legal question unresolved

`backend/scout/eviction_scraper.py`. California CCP §1161.2 masks unlawful
detainer records from public access for 60 days, and permanently where the
tenant prevails. Whether the scraped source is lawfully available has not been
confirmed. `[UNVERIFIED]` — this needs a lawyer, not a developer.

### 9.12 The test suite is red and cannot fully collect

Measured in this session: 2 files fail collection outright; of the rest,
**143 failed, 83 passed**.

To be fair to the code: the overwhelming majority of failures are missing
third-party packages in this container (`pipecat` ×35, `anthropic` ×15,
`fastapi` ×10, `supabase` ×29 and the 49 `backend.lib has no attribute db`
errors that cascade from it), **not** logic errors. The full dependency set
would not install here — `pip install -r requirements.txt` timed out.

What survives that caveat and is genuinely broken: the two collection failures
(9.10), the four `emotion` import errors (9.10), and one real assertion failure
(9.9). **`[UNVERIFIED]`: the true pass rate with all dependencies installed.**

### 9.13 `requirements.txt` pins nothing

Zero version specifiers across 30 packages — measured, not estimated. `pipecat-ai`
and `livekit-agents` are both fast-moving with breaking changes. Two installs a
week apart can produce different systems. `elevenlabs` is missing entirely
despite `ElevenLabsTTSService` being the canonical TTS in the pipeline doc.

### 9.14 Schedulers run inside the web process

`backend/api/main.py:139-204` starts an APScheduler `BackgroundScheduler` in the
FastAPI lifespan, with six cron jobs:

| Job | Schedule |
|---|---|
| Scout run | 7am, 12pm, 5pm |
| Outbound campaign | 9am, 1pm |
| Sophia loop | 10am, 2pm, 6pm |
| Daily drip triggers | 8:30am |
| Engagement refresh | 6am |
| Follow-up poller | every 30 min |

`Procfile` declares only `web`. So every job runs in the web dyno: scale to two
replicas and each job fires twice (`max_instances=1` is per-process, not
cluster-wide); a web restart kills in-flight work; a slow scrape degrades API
latency. `Sophia-Agent` runs `web`, `worker`, `dialer`, `discovery` as separate
processes, which is the correct shape.

### 9.15 Code comments violate the project's own rule

`AGENTS.md`: *"Never write comments in any code."* `backend/workflows/engine.py`
has three. Cosmetic, but it means the rule is not enforced anywhere, which is
how the bigger rules (cents, `db.py`-only access) erode too.

Also: `get_karoathys_state_snapshot()` — the authority system's name is
misspelled in a public function name and in four test class names.

### Which of these are actually dangerous

| | Defects |
|---|---|
| **Legal exposure** | 9.1, 9.2, and 9.11 pending a lawyer |
| **Security** | 9.3, 9.5 |
| **Silent data corruption** | 9.7, 9.8, 9.9 |
| **Cannot trust the build** | 9.4, 9.6, 9.12, 9.13 |
| **Operational** | 9.14 |
| **Hygiene** | 9.10, 9.15 |

---

## 10. Compliance

The part of this project that can cost real money if it is wrong.

| Rule | Source | Where enforced |
|---|---|---|
| Calling hours 8am–9pm **recipient's** timezone | TCPA | `compliance.py` — **broken, §9.2** |
| Do-Not-Call registry check | TCPA | `compliance.py` — **fails open, §9.1** |
| Honour STOP immediately and permanently | TCPA / CTIA | `leads.opted_out` — **over-applied, §9.8** |
| Disclose AI voice on request | FCC, Feb 2024 | `processors/ai_identity.py` — must be unconditional |
| No demographic / steering language | Fair Housing Act | `processors/fair_housing.py` ✓ |
| Eviction records may be masked | CA CCP §1161.2 | **Unresolved, §9.11** |
| Do not interfere with a listed seller's agent | CA tortious interference | `stale_listings.py` — **not in the trunk** |

### The stale-listing branch

`Sophia-Agent/backend/scout/stale_listings.py` decides who to contact on a
65+ day listing: `listing_agent`, `owner`, or `review`. If the listing is active
and there is no agent phone, the lead is **skipped** — it never falls back to
contacting the owner directly. Contacting a seller under an exclusive listing
agreement is how you get sued by their broker.

This module is not in the trunk yet.

### The kill switch

`opted_out=True` stops every outbound channel. It must be checked before calls,
SMS, email, voicemail and drip. **In the trunk, `alerts/` modules do not call a
consent gate before sending** — that is `REBUILD_MAP` items 86–97.

---

## 11. Data, configuration, deployment

### Tables (28, in the trunk's Supabase)

**Core** — `properties`, `leads`, `contacts`, `comps`, `calls`, `offers`

**Comms** — `sms_messages`, `email_sends`, `email_events`, `followups`,
`campaigns`, `deal_blast_sends`, `phone_pool_health`, `dnc_list`

**Intelligence** — `intel_packets`, `packet_events`, `decision_records`,
`bob_feedback_events`, `transcript_chunks`, `call_events`

**Governance / ops** — `approval_requests`, `operator_queries`, `tool_gate_log`,
`workflows`, `traces`, `eval_runs`, `latency_benchmarks`, `cash_buyers`

13 migrations in `supabase/migrations/`, dated 2026-05-04 through 2026-05-13.
`Sophia-Agent` has 10 more (`0004`–`0010`: voicemail, dispo, stale listings,
worker runs, seller facts, data quality, call priority) that must be renumbered
into the trunk sequence.

### Environment variables (~50, none declared in code)

**Required** — `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SIGNALWIRE_PROJECT_ID`,
`SIGNALWIRE_TOKEN`, `SIGNALWIRE_SPACE`, `SIGNALWIRE_PHONE`, `ANTHROPIC_API_KEY`
— these seven use `os.environ[...]` and raise at import if absent.

**Voice** — `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL`, `DEEPGRAM_TTS_MODEL`,
`CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`, `CARTESIA_MODEL`, `ELEVENLABS_API_KEY`,
`TOGETHER_AI_API_KEY`, `GROQ_API_KEY`, `LLM_MODEL`, `VOICE_LLM_MODEL`,
`VOICE_BASELINE_MODE`, `LATENCY_TARGET_MS`

**Data** — `BATCHDATA_API_KEY`, `CRMLS_API_KEY`, `CRMLS_MEMBER_ID`,
`REALESTATEAPI_KEY`

**Business** — `BUSINESS_NAME`, `BUSINESS_EMAIL`, `AGENT_FULL_NAME`, `AGENT_PHONE`, `OWNER_PHONE`, `ALERT_PHONE`

**Tuning** — `MAO_MULTIPLIER`, `MAO_REPAIR_BUFFER`, `CALLING_HOURS_START`,
`CALLING_HOURS_END`, `MIN_DISTRESS_SCORE_FOR_ALERT`, `SCOUT_CRON_INTERVAL_HOURS`

**Infra** — `KARPATHYS_URL`, `KARPATHYS_WEBHOOK_SECRET`, `SENDGRID_API_KEY`,
`SENDGRID_WEBHOOK_SECRET`, `REDIS_URL`, `PUBLIC_URL`, `RAILWAY_STATIC_URL`,
`LANGFUSE_*`, `LOG_LEVEL`, `SIGNALWIRE_PHONE_POOL`, `SIGNALWIRE_NUMBER_GROUP_ID`

**`.env.example` is empty.** Populating it is `REBUILD_MAP` item 12.

### Deployment

| Component | Host | Command |
|---|---|---|
| Backend | Railway | `uvicorn backend.api.main:app` |
| Dashboard | Vercel | Next.js |
| Database | Supabase | Postgres + RLS |
| Telephony | SignalWire | **Never Twilio** |

Health check `/api/health`, restart on failure, max 3 retries.

---

## 12. The plan

Ten gates. Nothing in a gate starts until the previous gate's tests pass. Full
detail and the `0/150` checklist are in `REBUILD_MAP.md`.

| Gate | Deliverable | State |
|---|---|---|
| **1** | V2 constitution ratified | Written; **8 open decisions block it** |
| **2** | Rebuild map | Written; 6 items remain |
| **2.5** | The live defects | **Not started — do this first** |
| **3** | Karpathys hardened | Not started |
| **4** | Shared infrastructure — outbox, ledgers, `may_contact()` | Not started |
| **5** | Merge the donor into the trunk (36 modules) | Not started |
| **6** | Resolve the triplication | Not started |
| **7** | Route every side effect through the Orchestrator | Not started |
| **8** | Contracts and staleness | Not started |
| **9** | Learning layer | Not started |
| **10** | Controlled real calls | Not started |

### Gate 2.5 — the seven fixes that do not wait

None of these depend on any architectural decision. They are bugs in deployed
code and they can be done in about a week.

1. `_check_dnc` fails closed (9.1)
2. Recipient-timezone calling hours, all six call sites (9.2)
3. Authenticate or delete the dashboard ingest routes (9.3)
4. Karpathys ingest denies on unset secret (9.5)
5. `backend/lib/config.py`; startup fails loudly on missing vars (9.6)
6. Populate `.env.example` (9.6)
7. Move `test_env_example.py` over so 6 cannot rot (9.6)

### How autonomy gets earned

```
inbound only → outbound to testers → outbound with per-call human approval
             → autonomous within tight caps → graduated caps
```

Autonomous outbound is last — not because the code will not be ready, but
because the evidence that it behaves well does not exist until the earlier
stages produce it.

---

## 13. Decisions waiting on you

Eight. Each has a recommendation in `REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md` §18.

| # | Decision | Recommendation |
|---|---|---|
| **A** | Monorepo or separate repos? | Monorepo — `REI-AGENT` already is one |
| **B** | Does `Sophia-Agent` V1 stay running? | Yes, frozen, as the fallback |
| **C** | Which Bob survives? | Per module, not per repo — §8 |
| **3.1** | Service transport | HTTP + outbox first; message bus only if scale demands |
| **7.1** | Frequency caps per person | 1 call + 1 text/day, 3 calls/week, 30-day quiet after "not interested" |
| **8.1** | Do seller-stated facts decay? | Yes for condition, never for intent |
| **10.1** | May Sophia make a binding offer? | No, not in V2 |
| **14.1** | Approval quorum with one operator | Single approver, structure retained |

**A is the one that matters most.** Every `MOVE` arrow in the rebuild map
reverses if you name a different trunk.

---

## 14. Hard rules

From `AGENTS.md`, non-negotiable:

- **No comments in Python** — not inline, not block, not docstrings. SQL migrations may use `--`.
- **SignalWire only.** Never Twilio.
- **All Supabase access through `backend/lib/db.py`.**
- **`from backend.lib import db` then `db.fn()`** — never `from backend.lib.db import fn`, which breaks monkeypatching in tests.
- **Never commit `.env` files** — not even with placeholder values.
- **All money in integer cents.** ARV and MAO are integers, never floats.
- **`loguru` for all logging.** Never `print()`.
- **Every env var the code reads is declared in `config.py` and mirrored in `.env.example`.**
- **No business logic in API routes.**
- **Never import from `scripts/`.**

Currently violated: comments (9.15), cents (9.9), config declaration (9.6).

---

## 15. An honest assessment

### What is genuinely good

The typed `CallBrief` contract. The checkbox ladder — one objective per call is
the right model and most competitors get it wrong. The processor stack is real
engineering: smart-turn-adjacent VAD tuning, fair-housing filtering, AI
disclosure, backchannel injection, sentence streaming. `Sophia-Agent`'s
compliance layer is better than most commercial dialers. Karpathys' governance
module list is the right list.

### What is not

Four repositories with three copies of Bob and three of Sophia. A test suite
that cannot collect. An empty `.env.example` against 50 environment variables.
A DNC check that fails open. A governance flag that fires on every deal. Six
scheduled jobs living inside a web process.

None of that is exotic. It is the ordinary result of building fast in four
places at once, and every item has a named fix.

### The thing worth saying plainly

**This system has never placed a live call.**

Roughly 20,000 lines of Python, four architecture documents, 150 planned work
items, and zero conversations with a real seller. Every estimate in this
project — whether Sophia sounds human, whether the ladder survives a real
objection, whether sellers hang up on the AI disclosure, whether the scoring
finds motivated owners or just distressed ones — is currently a guess.

Gate 2.5 takes about a week and makes the live system legally safer. Gates 3–10
take months and make it durable.

If the goal is a durable system, follow the map in order.

If the goal is revenue this quarter, the sequence I would actually recommend is:
**do Gate 2.5, place one real call, then read this document again.** One real
conversation will tell you more about what to build than any of these three
documents can — including which of the 150 items turn out not to matter.

Those are different goals and only you can say which one this quarter is for.

---

*Maintained alongside `REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md` (what it should
be) and `REBUILD_MAP.md` (how to get there). When code and these documents
disagree, the documents are stale — fix them.*
