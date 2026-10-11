# Brutal Grade — Every System, End to End

**Date:** 2026-10-11 · **Commit:** `11fd8fc` · **Branch:** `claude/project-visibility-8cah98`

Measured, not recalled. Every number below came from an AST pass, a grep, or a
test run in this session. Unverifiable claims are marked `[UNVERIFIED]`.

---

## Overall: **D**

Down from D− only because the emergency containment landed. Up from nothing
because the conversation engineering is genuinely good.

The grade is not "the code is bad." The grade is this:

> **63% of the codebase has never been tested, 135 database queries are
> unbounded, the dashboard has no authentication on any page, and the
> containment that fixes the worst defects is sitting on a branch that was
> never merged.**

---

## The measurements

| Metric | Value |
|---|---|
| Python modules | 118 |
| Backend LOC | 20,197 |
| **Modules never referenced by any test** | **74 of 118 (63%)** |
| Broad/bare exception handlers | 247 |
| …that swallow with bare `pass` | 34 |
| `.table()` calls | 203 |
| `.limit()` calls | 68 |
| **Unbounded queries** | **~135** |
| Longest function | **158 lines** (`voice/agent.py`) |
| Second longest | **134 lines** (`lib/batchdata.py`) |
| Routes | 81 |
| Routes with authentication | **0** |
| Dashboard files with authentication | **0 of 17** |
| Tables created by migrations | 6 of 28 |
| Scrapers checking `robots.txt` | **0 of 7** |
| Scrapers with retry logic | **0 of 7** |
| Writers to the single `runtime_instruction` slot | **16, across 8 files** |
| Containment commits merged to master | **0 of 8** |

---

## System grades

### 🟢 Conversation engineering — **B+**

The best thing here, and it is not close.

`voice/processors/` is 20 modules of real work: STT muting during bot speech,
interruption acknowledgement, backchannel injection, sentence streaming on
comma boundaries, fair-housing filtering, phone EQ, breath injection. The VAD
is tuned to `stop_secs=0.5` rather than Pipecat's 0.2 default, which is the
difference between a conversation and cutting people off. The 800 ms latency
target sits correctly inside the 500–1,200 ms natural window.

`geo_phrases.py` is 216 lines of Stockton-specific local reference. Somebody
who knows the market wrote that.

**Why not an A:** every one of the 11 cognition modules — trust, momentum,
resistance, seller profile, deal heat, microstate, emotional state, fatigue,
objective, turn controller, runtime orchestrator — has **zero tests.** Eleven
interacting scoring systems, no coverage, never run against a real seller.

### 🟢 Strategy layer (Bob) — **B−**

`contracts/call_brief.py` is the single best-designed file in the repository:
closed `Phase` enum, closed `MissingBox` enum, explicit `to_dict`/`from_dict`,
no mutable defaults. The checkbox ladder — one objective per call — is a better
model than most funded competitors ship.

**Why not higher:** all five `call_planner` modules have **zero tests**, and
the trunk's `brief_generator.py` is a 58-line stub against 136- and 141-line
siblings in two other repos. The trunk cannot derive phase, mood, or
confidence. The strategy brain is the least tested part of the system.

### 🟡 Underwriting / comps — **C+**

`comps/calculator.py` does real work: weighted price-per-square-foot, standard
deviation, price variance, confidence scoring, stale-comp and distant-comp
penalties, `comp_strength` bands at 0.05 and 0.12 variance.

Then it throws almost all of it away.

| Signal computed | Files that read it |
|---|---|
| `confidence` | 14 |
| `price_variance` | **0** |
| `comp_strength` | **0** |
| `stale_comp_count` | **0** |
| `distant_comp_count` | **0** |
| `neighborhood_liquidity` | **0** |

A comp set with 40% price variance produces the same offer as one with 3%. The
uncertainty is measured and discarded — in the money path.

And `_get_offer_range` quotes a live dollar figure to a seller like this:

```python
arv = arv_raw if arv_raw > 10000 else arv_raw * 100     # unit guess by magnitude
mao = mao_raw if mao_raw > 10000 else mao_raw * 100
low  = int(mao * 0.95)
high = int(mao * 1.05)
```

Three defects in four lines: units are **guessed from magnitude** rather than
known; `arv` is assigned and never used again; and the ±5% band is cosmetic —
it is not a valuation range, it ignores every uncertainty signal above, and it
is identical for a strong and a weak comp set.

Zero tests on any of `calculator.py`, `redfin.py`, `homeharvest.py`, `cache.py`.

### 🟡 Lead generation — **C**

Eleven sources and thoughtful scoring. `scout/scorer.py` has defensible weights
— NTS +65, pre-foreclosure +55, vacant +42 — with combination bonuses that
show real domain understanding (vacant + pre-FC +28).

`scout/scorer.py` has **zero tests.** So does `parser.py`. So do all seven
scrapers.

Scraper resilience, measured:

| | court | tax | eviction | crmls | social | rss | cash_buyer |
|---|---|---|---|---|---|---|---|
| robots.txt | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| retry/backoff | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| timeout | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| user-agent | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |

Hardcoded HTML selectors in six files. A site redesign silently returns zero
leads, and with 34 bare-`pass` handlers nothing tells you.

Still missing from the trunk: the canonical `intake.py`, `validate.py`,
`skiptrace.py` and `stale_listings.py` that live unmerged in `Sophia-Agent`.

### 🔴 Data integrity — **F**

- **~135 unbounded queries.** 203 `.table()` calls, 68 `.limit()`.
- `db.py` is 1,339 lines, 85 functions, 97 table calls, 17 limits.
- Lost-update races on `call_attempts` and `contact_attempts` (read-modify-write).
- Double-dial race: `last_called_at` written at outcome, not at claim.
- Write-only fields: `priority_callback` (the HOT signal — 2 writes, 0 reads),
  `expires_reason`, `resolved_at`, `total_closed`.
- Five comp-quality signals, above, computed and never read.

The pattern is consistent and it is the single most useful thing to know about
this codebase: **things are computed and nothing consumes them.**

### 🔴 Security — **F**

| | |
|---|---|
| Routes | 81 |
| Authenticated | **0** |
| Webhook signature verification | **0 of 4** SignalWire endpoints |
| Rate limiting | none |
| Payload limits | none |
| Dashboard pages with auth | **0 of 17** |
| `middleware.ts` | **does not exist** |
| Service key exposure | 4 Next.js ingest routes |

The four `dashboard/app/api/ingest/*` routes accept unauthenticated POSTs and
write to Supabase with the service key, which bypasses RLS.

Credit where due: no `eval`, `exec`, `pickle`, `os.system`, or `subprocess`
anywhere. No raw SQL interpolation — everything goes through the Supabase
client, so injection is structurally unavailable. Seller speech is delimited in
`<seller>` tags before reaching the model. Those are the vulnerabilities that
end companies and they are absent.

### 🔴 Compliance — **D+**, up from F

The containment earned this. Truthful AI disclosure across seven prompt files,
`honor_stop_request` as an unconditional suppression primitive, append-only
evidence, post-STOP lockout, tenant hard-deny, deny-by-default tool gating.

Still failing:

- **Disclosure is prompt-resident**, so a legal obligation is model-discretionary.
- `_check_dnc` still fails open on a database exception.
- Calling hours still hardcode `America/Los_Angeles` in six places. 21:00
  Pacific is midnight Eastern.
- No consent capture at all, against an FCC ruling that likely requires prior
  express **written** consent for AI voice.
- No recording disclosure in a two-party-consent state.
- `compliance_output_filter.py` is a phrase linter, not a boundary — and it has
  zero tests.
- `input_guard.py` — the jailbreak detector — has zero tests, and still carries
  the old evasive line `"Ha — I'm just Sophia."`

And the kill-switch architecture is still broken: **16 writers across 8 files
share one `runtime_instruction` string slot.** A DNC kill switch, a jailbreak
detection, and a "seller is venting, respond with warmth" nudge all compete for
the same field, last write wins.

### 🔴 Testing — **F**

**74 of 118 modules have zero test reference.** Not thin coverage — zero.

Untested, in full: all 5 Bob planner modules · all 4 comps modules · all 7
scrapers · `scout/scorer.py` · `scout/parser.py` · `qa/grader.py` ·
`qa/metrics.py` · `voice/webhook.py` (the inbound entry point) ·
`voice/outbound_webhook.py` · all 11 cognition modules · both safety processors
· `lib/batchdata.py` · `observability.py` · all 3 eval modules · 7 of 9
`alerts/` modules.

Two test files still cannot collect — they import
`backend.voice.processors.spoken_renderer`, which does not exist. Four more
import `.processors.emotion`, which does not exist.

The 58 containment tests I added are the only adversarial coverage in the repo.

### 🔴 Reliability — **D−**

Live call state lives in process memory: `app.state.call_contexts`,
`call_metrics`, `call_started_at`. **The system cannot run two replicas** — a
webhook can land on a replica with no context for the call — and a restart
drops every call in flight. Nothing in the code or docs says so, which makes
scaling up the action that breaks it.

Six APScheduler jobs run inside the web process. `max_instances=1` is
per-process, not cluster-wide.

Zero retry or backoff on any external call — Deepgram, Anthropic, ElevenLabs,
SignalWire, BatchData, Supabase. `tenacity` is installed and `@retry` appears
nowhere.

### 🔴 Platform / reproducibility — **F**

6 of 28 tables created by committed migrations. The schema of record for
`leads`, `properties`, `calls`, `contacts`, `sms_messages`, `dnc_list` and 16
others is **not in version control.** A clean environment cannot be built from
this repository.

Zero version pins across 30 dependencies, including `pipecat-ai` and
`livekit-agents`, both of which ship breaking changes. `elevenlabs` is missing
entirely despite being the canonical TTS. No CI, no Dockerfile, no pytest
config, no lint config, no branch protection.

### 🟡 Observability — **C−**

Langfuse wired, `observability.py` compares against `LATENCY_TARGET_MS`,
`latency_tracker.py` measures the full UserStopped → TTS chain.

But nothing aggregates: no p50, no p95, no p99, no false-endpoint rate, no
interruption cutoff latency. Per-call logging cannot show you the p99 that
produces your worst calls, and tail latency is what sellers remember. No cost
tracking at all — `enable_usage_metrics=True` is set and nothing persists it,
so the unit economics of the entire business are unmeasured.

`observability.py` has zero tests.

### 🟡 Dashboard — **D**

2,911 lines of TSX across 17 files, zero authentication, no middleware. Several
pages are substantial — `leads/[id]/page.tsx` is 686 lines, `calls/[id]` is
343, `workflow` is 295 — and all of them read production seller data with no
access control `[UNVERIFIED: whether Vercel sits behind an access gate]`.

Missing versus the `Sophia-Agent` dashboard: `/health`, `/reasoning`,
`/discovered`, `/buyers`, the public `/sell` form, auth middleware, and 9
components. Trunk has 1 component total.

### 🟢 Documentation — **A−**

Seven documents, measured rather than asserted, with corrections recorded when
I got things wrong. `MASTER_REFERENCE.md`, `AUDIT_AND_GRADE.md`,
`SECOND_AUDIT_VERIFICATION.md`, `REBUILD_MAP.md`, `EMERGENCY_CONTAINMENT.md`,
`ROADMAP.md`, `PII_PURGE_RUNBOOK.md`.

**One live contradiction:** `AGENTS.md` — the file every contributor and agent
reads first — still specifies `Name: Sophia Reyes / Age: 25, born and raised in
Stockton / went to Lincoln High / Delta College`. That is the exact fabricated
human identity removed from all seven prompt files for SB 1001 reasons. Anyone
following AGENTS.md as written reintroduces the deception.

### 🔴 Delivery — **F**

**All 8 containment commits are unmerged.** `origin/master` still has:

```
sophia_runtime.md:2  "You are Sophia Reyes. 25. Stockton born and raised…"
execution_context.py  ABSENT
honor_stop_request    0 occurrences
```

If Railway deploys master — the common default — the deceptive prompt, the
model-supplied `lead_id`, and the fail-open tool gate are all still live.
`[UNVERIFIED: which branch Railway tracks]`. This is the highest-value unknown
in the project and it takes thirty seconds to check.

---

## Worst files

| File | LOC | Longest fn | Blind except | Silent `pass` | Grade |
|---|---|---|---|---|---|
| `lib/db.py` | 1,339 | 45 | 9 | 1 | **D** — 97 table calls, 17 limits |
| `voice/agent.py` | 1,129 | **158** | 14 | 2 | **C−** — good pipeline, unreviewable function |
| `voice/tools.py` | 944 | 65 | 25 | **10** | **C** — hardened, still 10 silent swallows |
| `processors/context_tracker.py` | 642 | 64 | 3 | 2 | **C** — does too much |
| `lib/osm.py` | 495 | 51 | 6 | 0 | **C−** — untested, 5 HTTP calls, no retry |
| `alerts/drip.py` | 485 | 48 | 7 | 3 | **D** — untested, no consent gate |
| `voice/outbound.py` | 411 | 79 | 14 | **5** | **D** — 11 env reads, Pacific-hardcoded |
| `lib/batchdata.py` | 404 | **134** | 6 | 1 | **D** — untested skip trace |
| `scout/scorer.py` | 316 | 71 | 1 | 0 | **C+** — good weights, zero tests |
| `api/routes/email_webhook.py` | 238 | 27 | 11 | 0 | **D** — wrong auth primitive, fails open |

### Best files

| File | Why |
|---|---|
| `contracts/call_brief.py` | Closed enums, explicit serialization, no mutable defaults. **A−** |
| `comps/calculator.py` | Real underwriting math. **B**, dragged down by discarded outputs |
| `voice/execution_context.py` | Written this session; 0 lint, fully tested. **A−** |
| `scout/scorer.py` weights | Domain knowledge visible in the combination bonuses |
| `voice/geo_phrases.py` | 216 lines of genuine local knowledge |

---

## New defects this pass

Continuing the register from 69.

**70.** ~135 unbounded queries repo-wide (203 `.table()` vs 68 `.limit()`) —
materially worse than the earlier `db.py`-only estimate of 78.

**71.** Five comp-quality signals computed and read by zero files:
`price_variance`, `comp_strength`, `stale_comp_count`, `distant_comp_count`,
`neighborhood_liquidity`. Measured uncertainty discarded in the money path.

**72.** `_get_offer_range` guesses money units by magnitude (`> 10000`),
assigns `arv` and never uses it, and quotes a cosmetic ±5% band around MAO that
ignores measured variance.

**73.** 74 of 118 modules (63%) have zero test reference, including every Bob
planner module, every comps module, every scraper, the inbound webhook, all 11
cognition modules, and both safety processors.

**74.** Dashboard: zero authentication across 17 files, no `middleware.ts`,
service key in 4 unauthenticated ingest routes.

**75.** 0 of 7 scrapers check `robots.txt`; 0 of 7 retry; 2 of 7 have neither
timeout nor user-agent.

**76.** A 158-line function in `voice/agent.py` and a 134-line function in
`lib/batchdata.py`.

**77.** 16 writers to the single `runtime_instruction` slot across 8 files —
refines §9.19 upward from 11. Safety-critical instructions and tone nudges
share one string.

**78.** `input_guard.py` — the jailbreak detector — has zero tests and still
carries the pre-containment evasive line `"Ha — I'm just Sophia."`

**79.** `comps/calculator.py` performs float arithmetic on money
(`arv_dollars = weighted_ppsf * subject_sqft`) before converting to cents,
against the AGENTS.md rule "ARV and MAO always integers never floats."

**80.** `AGENTS.md` still specifies the fabricated human identity that was
removed from every prompt file. The instruction file contradicts the fix.

**81.** All 8 containment commits unmerged; `origin/master` retains the
deceptive prompt and the fail-open tool gate.

**Register total: 81 distinct findings.**

---

## Grade distribution

| Grade | Systems |
|---|---|
| **A−** | Documentation |
| **B+** | Conversation engineering |
| **B−** | Strategy layer (Bob) |
| **C+** | Underwriting / comps |
| **C** | Lead generation |
| **C−** | Observability |
| **D+** | Compliance |
| **D** | Dashboard |
| **D−** | Reliability |
| **F** | Data integrity · Security · Testing · Platform · Delivery |

Five F's. Three of them — testing, platform, delivery — are not about the code
being wrong. They are about nobody being able to tell whether it is right.

---

## The verdict

**What is genuinely good:** the conversation engineering, the typed `CallBrief`,
the scoring weights, the comps math, the absence of any injection or
deserialization vulnerability, the 800 ms latency target, and documentation more
candid than most companies produce.

**What is genuinely bad:** no authentication anywhere, 63% of modules untested,
135 unbounded queries, a dashboard with no access control, a schema that cannot
be rebuilt, a system that silently cannot scale past one machine, and
uncertainty that is carefully measured and then thrown away.

**The one sentence:** this project is a well-engineered set of components
connected by nothing, measured by nothing, and guarded by nothing — and the
fixes for the worst of it are already written and sitting on an unmerged branch.

**The cheapest three things, in order:**

1. **Check which branch Railway deploys.** Thirty seconds. If it is master,
   nothing you fixed is live.
2. **Merge the branch.** Eight commits, 58 passing tests, zero regressions.
3. **Fix the four AGENTS.md lines** so the next contributor does not undo it.

And the largest fact remains unchanged from every prior audit: **20,197 lines,
81 findings, and still zero conversations with a real seller.** Every estimate
in this project is a guess until that changes.
