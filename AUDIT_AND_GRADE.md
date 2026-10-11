# Brutal Audit & Grade

**Date:** 2026-09-11 · **Method:** read the code, ran the suite, researched the
regulatory position. Nothing here is recalled or assumed. Unverifiable claims
are marked `[UNVERIFIED]`.

**Companion documents:** `MASTER_REFERENCE.md` (what exists),
`REAL_ESTATE_AI_OPERATING_SYSTEM_V2.md` (what it should be),
`REBUILD_MAP.md` (how to get there).

---

## 0. The verdict, up front

### Overall: **D+**

Not because the code is bad. Substantial parts of it are genuinely good. The
grade is what it is because of four things:

1. **The business model may be illegal as designed.** Research below: an AI
   voice cold-calling consumers is an "artificial voice" robocall under the
   TCPA. That requires *prior express written consent* — and an established
   business relationship does **not** exempt it. Exposure is $500–$1,500 per
   call with no aggregate cap. The system has no consent capture at all.
2. **Hot leads go nowhere.** `priority_callback` is set on every HOT
   disposition and every escalation, and **nothing in the codebase reads it.**
   A seller who says "call me Tuesday" sorts identically to a cold record.
3. **There is no authentication anywhere.** 28 POST endpoints, zero auth, zero
   rate limiting, zero webhook signature verification.
4. **It has still never placed a live call.**

### What the grade is *not* saying

The conversation engineering is real. The checkbox ladder is a better model
than most funded competitors ship. `CallBrief` is a properly designed contract.
Somebody thought hard about this. The problem is that nothing has ever been
tested against reality, and the seams between the good parts are where every
defect lives.

---

## 1. Report card

| Area | Grade | One-line reason |
|---|---|---|
| Product vision | **A−** | Correct insight: one objective per call, seller state over scripts |
| Conversation engineering | **B+** | 11 cognition modules, fair-housing filter, backchannel, sentence streaming — real work |
| Bob / strategy layer | **B−** | Excellent contract design, but the trunk's copy is a stub (§3 of the map) |
| Lead generation | **B** | 11 sources, thoughtful scoring weights; no canonical intake path in the trunk |
| Pricing / underwriting | **C+** | MAO formula is sound; the conflict detector is unit-broken and always fires |
| Data integrity | **D** | Write-only fields, lost-update races, no validation layer in the trunk |
| **Compliance** | **F** | Fails open on DNC, wrong timezone, reactive-only AI disclosure, no consent capture, no recording notice |
| **Security** | **F** | No auth, no webhook signatures, no rate limits, unauthenticated ingest writing to the system of record |
| Reliability | **D−** | Cannot run more than one replica; live calls die on restart |
| Testing | **D** | Suite red; 2 files import modules that do not exist |
| Observability | **C−** | Langfuse + latency tracking wired, but no percentiles and no cost tracking |
| Code discipline | **C** | Own rules violated: comments, cents, config declaration |
| Documentation | **A−** | Genuinely excellent and unusually honest — four solid documents |
| **Business readiness** | **F** | Zero live calls, zero revenue, unit economics unmeasured |

**Weighted overall: D+.** Documentation and vision carry it off an F.

---

## 2. The finding that changes the plan

### AI voice cold-calling needs written consent. You have none.

The February 2024 FCC ruling classifies AI-generated voices as "artificial
voice" under the TCPA. Consequences, from the research below:

| | |
|---|---|
| **Consent standard** | Prior express **written** consent for telemarketing |
| **EBR exemption** | Does **not** apply — the AI voice itself triggers the obligation regardless of relationship |
| **Damages** | $500–$1,500 per call, trebled if willful, **no aggregate cap** |
| **Recent settlements** | $5M–$20M range in 2025–2026 class actions |
| **Mild relief** | The one-to-one consent rule was struck down; multi-seller consent remains legal |

The system's entire premise — scrape distressed owners, skip trace their
numbers, dial them with a synthetic voice — is the **highest-risk possible
configuration** under this rule. Its only gate is "are they on the DNC list,"
which is the wrong standard, and that gate fails open anyway (§9.1 of
`MASTER_REFERENCE.md`).

Scale makes it worse, not better. 1,000 calls at the low end is $500,000 of
statutory exposure.

> **I am not a lawyer and this is not legal advice.** But the gap between "not
> on the DNC list" and "prior express written consent" is wide enough that it
> needs a TCPA attorney's opinion **before** the first outbound call, not
> after. This is the cheapest item on the list and the only one that can end
> the business.

### California adds a second problem

`backend/voice/processors/ai_identity.py` names its constant
`_SB1001_DISCLOSURE`, so the intent to comply is explicit. The implementation
does not match it:

```python
if _AI_QUESTION.search(text) and not self._disclosed:
    self._ctx.runtime_instruction = (
        f"[Seller asked if you are AI. Respond exactly: '{_SB1001_DISCLOSURE}']"
    )
```

Two defects in four lines:

1. **It only fires when the seller asks.** SB 1001 requires disclosure at the
   *beginning* of the interaction. A seller who never asks never learns.
2. **It is a suggestion to the model.** The disclosure is injected as a prompt
   instruction, so a legal obligation depends on the LLM choosing to comply.
   The V2 spec's own invariant #12 — "STOP conditions are enforced outside the
   model" — applies with equal force here.

There is also **no recording or transcription disclosure anywhere**, and
California is a two-party consent state. The system writes full transcripts to
`transcript_chunks`. `[UNVERIFIED]` whether real-time transcription without
audio retention constitutes recording under Penal Code §632 — another question
for the attorney, in the same conversation.

### What this means strategically

If the attorney confirms this reading, outbound AI cold-calling is not
available to you, and four alternatives are:

| Model | Why it survives | Cost |
|---|---|---|
| **Inbound-first** — direct mail, PPC, SEO, signs drive sellers to call *you*; Sophia answers | The seller initiated. Cleanest position by a wide margin | Marketing spend replaces list spend |
| **Consent-gated outbound** — capture written consent via the web form, then Sophia calls | Compliant by construction | Much smaller top of funnel |
| **Human-dialed, AI-assisted** — a person dials and speaks; AI listens, coaches, and writes the record | No artificial voice, so the robocall rules never attach | Needs a human on every call |
| **Text-first with opt-in** — SMS opt-in, then call | Consent captured before voice | SMS has its own TCPA rules |

**The inbound path deserves serious thought.** Nearly everything already built
— the whole conversation stack, Bob's ladder, the seller-state modelling —
works identically on an inbound call. What changes is the top of the funnel,
not Sophia. The `/sell` form in `Sophia-Agent` is already the beginning of it.

**Note the irony:** the system is safest doing the thing it has never tried.
Inbound is both the lowest-risk path and the fastest way to a first real
conversation.

---

## 3. New defects found this session

Fifteen more, on top of the fifteen in `MASTER_REFERENCE.md` §9. Numbering
continues from there.

### 9.16 — Hot leads and escalations do not move up the call queue

**The worst logic bug in the system.**

`backend/lib/db.py:359` (HOT disposition) and `:911` (`escalate_lead`) both set
`priority_callback = True`. Grepped across `backend/`, `dashboard/`, `scripts/`
and `supabase/`: **two writes, zero reads.** The column exists in
`20260505_add_disposition_appt_columns.sql` and nothing selects it, filters it,
or sorts by it.

The call queue is `get_leads_for_outbound`, and it sorts like this:

```python
results.sort(
    key=lambda r: r.get("composite_score") or (r.get("properties") or {}).get("distress_score", 0),
    reverse=True,
)
```

So a seller who said "call me back Tuesday" competes on distress score alone.
`escalated=True` is read — but only to render a badge in the dashboard
(`leads/[id]/page.tsx:224`) and in one workflow query. It changes nothing about
who gets dialed.

This is exactly the bug `Sophia-Agent/bob/prioritizer.py` was written to fix,
by making "waiting on a human" a **tier** rather than a score bonus. That
module is sitting unmerged in the donor repo.

### 9.17 — Zero webhook signature verification

Grepped `voice/webhook.py`, `voice/outbound_webhook.py`, `api/routes/sms.py`,
`api/routes/sms_status.py` for `signature`, `hmac`, `sha1`, `sha256`,
`validate_request`: **no matches in any of them.**

SignalWire signs its webhooks. Nothing checks. Anyone who learns the URL can
POST a fake inbound call, inject a transcript, trigger a disposition, or mark a
lead dead.

### 9.18 — 28 POST endpoints, no authentication, no rate limiting

`backend/api/main.py` has no `Depends`, no `APIKeyHeader`, no `HTTPBearer`, no
auth middleware. Grepped for `ratelimit`, `slowapi`, `Limiter`: nothing.

Combined with 9.17 and with 9.3 (the unauthenticated dashboard ingest routes),
**there is no authentication anywhere in the system.**

### 9.19 — Safety instructions silently overwrite each other

`runtime_instruction` is a **single string field** on the call context, written
by **eleven** different places and cleared after one read
(`context_tracker.py:321-323`).

Among the writers:

| Writer | Instruction |
|---|---|
| `context_tracker.py:431` | `[DNC: call set_disposition(DEAD) then end_call immediately.]` |
| `analysis_callbacks.py:152` | `[Kill switch triggered. Route to safe fallback.]` |
| `ai_identity.py:34` | The SB 1001 disclosure |
| `turn_controller.py:63` | `[Seller is venting. Respond with warmth...]` |

If two fire in the same turn, **the last write wins and the others vanish.** A
DNC kill switch can be silently clobbered by an empathy nudge. The safety-
critical channel and the tone-adjustment channel are the same one-slot field.

### 9.20 — Two workers can dial the same seller

`get_leads_for_outbound` filters on `last_called_at` older than 72 hours or
null. But `last_called_at` is only written by `update_lead_call_outcome` —
i.e. **after the call completes.** Nothing claims the lead at selection time.

Two scheduler runs, or two web replicas (see 9.22), both see the same lead as
callable and both dial. To the seller that is two AI calls minutes apart, which
is both a terrible experience and additional TCPA exposure.

### 9.21 — Lost-update race on `call_attempts`

`db.py:335-341` reads `call_attempts`, adds one in Python, writes it back.
Classic read-modify-write. Concurrent calls lose increments, so attempt caps
built on this field undercount. Same pattern at `db.py:155` for
`contact_attempts`.

### 9.22 — The system cannot run more than one instance

Live call state lives in process memory:

```
app.state.call_contexts[call_sid]     voice/webhook.py
app.state.call_metrics[call_sid]      voice/webhook.py, outbound_webhook.py
app.state.call_started_at[call_sid]   voice/outbound_webhook.py
```

With two replicas behind a load balancer, a webhook for a call can land on the
replica that has no context for it. A Railway restart drops every call in
flight. Combined with §9.14 (six APScheduler jobs inside the web process, where
`max_instances=1` is per-process and not cluster-wide), **the system is
single-instance by construction — and nothing in the code or docs says so.**

That is a deployment landmine: scaling up to handle load is the action that
breaks it.

### 9.23 — 78 of 94 database queries are unbounded

94 `client.table(...)` calls, 16 `.limit(...)`. `get_leads_for_outbound` pulls
every callable lead into Python and filters there. Fine at 500 leads, a
memory event at 500,000.

### 9.24 — No cost tracking

`enable_usage_metrics=True` is set on the Pipecat pipeline and nothing persists
or aggregates it. There is no way to answer "what does a call cost" or "what did
we spend last month."

For a business whose viability is a per-call-cost question — STT + LLM + TTS +
telephony per minute against contracts closed — **not measuring this means the
unit economics are unknown.** That is a business defect, not a technical one.

### 9.25 — `tenacity` installed, `@retry` never used

No decorator, no backoff, no circuit breaker on any external call — Deepgram,
Anthropic, ElevenLabs, SignalWire, BatchData, Supabase. A transient 429 or 503
fails the operation outright.

Second dependency installed for a feature that was never wired, after
`livekit-agents[turn-detector]` (§7 of `MASTER_REFERENCE.md`).

### 9.26 — 246 broad exception handlers, 30 silent

`except Exception` appears 246 times across 137 files — roughly 1.8 per file.
Thirty swallow with a bare `pass`. This is the same mechanism as §9.7 (events
lost silently), generalized across the codebase: **failures do not surface, they
accumulate.**

### 9.27 — Latency is logged but never aggregated

`processors/latency_tracker.py` measures UserStopped → STT → TTS_start →
TTS_audio per call and logs it. `observability.py:176` compares against
`LATENCY_TARGET_MS` (default 800ms — a well-chosen target, see §4).

But nothing computes **p50, p95, or p99**, and nothing tracks **false endpoint
rate** — turns where the agent started speaking before the seller finished.
Per the research below, that pairing is the whole game: a fast average with
frequent false endpoints is an impatient agent, not a responsive one, and it is
invisible to per-call logging.

### 9.28 — Prompt injection surface is delimited but not escaped

Credit where due: seller speech is wrapped —
`f"<ctx>\n{prefix}\n</ctx>\n<seller>{content}</seller>"`
(`context_tracker.py:556`) — which is the right pattern and better than most
production systems.

The content is not escaped, so a literal `</seller>` in the transcript would
break the frame. Low severity on a voice channel (STT rarely emits angle
brackets) but it becomes real the moment this path accepts SMS, email, or web
form text, all of which are planned.

### 9.29 — No idempotency on call webhooks

`app.state.call_contexts[call_sid] = context` overwrites unconditionally.
SignalWire retries webhooks on non-2xx. A retried `call_started` resets live
call state mid-conversation. `The-Dashboard`'s ingest dedupes on
`provider_call_id`; the trunk does not.

### 9.30 — Three more write-only fields

Verified by checking writes against reads in `select` / `eq` / `order` / `get`
across backend and dashboard:

| Field | Writes | Reads |
|---|---|---|
| `priority_callback` | 2 | **0** — see 9.16 |
| `expires_reason` | 1 | **0** |
| `resolved_at` | 1 | **0** |
| `total_closed` | 1 | **0** |

`drip_paused`, `contact_attempts`, `last_contact_at`, `voicemail_script`,
`drip_completed` and `callback_from_voicemail` were initially flagged by the
same sweep and are **not** defects — each is read somewhere. Recorded here so
nobody re-runs the sweep and re-reports them.

### Not found — the good news

No `eval`, `exec`, `pickle`, `os.system`, or `subprocess` anywhere. No raw SQL
string interpolation; everything goes through the Supabase client, so SQL
injection is structurally unavailable. Seller input is delimited before it
reaches the model. These are the vulnerabilities that end companies, and they
are absent.

---

## 4. What the research says

### Regulatory

| Finding | Source |
|---|---|
| AI-generated voices are "artificial voice" under the TCPA (FCC, Feb 2024); all robocall rules apply in full | [Henson Legal](https://www.henson-legal.com/ai-voice-compliance) |
| Telemarketing by AI voice requires **prior express written consent**, documented before the call | [Retell AI](https://www.retellai.com/blog/tcpa-compliance-playbook-voice-ai-outbound) |
| An Established Business Relationship exempts manual calls from DNC rules but **does not** exempt AI voice from consent | [Henson Legal](https://www.henson-legal.com/ai-voice-compliance) |
| $500–$1,500 statutory damages per call, trebled if willful, **no aggregate cap** | [Revmo AI](https://revmo.ai/blog/tcpa-compliance-guide-ai) |
| 2025–2026 class actions settled in the $5M–$20M range | [Vida](https://vida.io/blog/tcpa-2026-what-changed) |
| The one-to-one consent rule was struck down; multi-seller consent remains legal | [Vida](https://vida.io/blog/tcpa-2026-what-changed) |
| Stricter state law governs where it exists | [Klariqo](https://klariqo.com/blog/tcpa-compliance-ai-voice-agents/) |
| CA SB 1001 requires bot disclosure **at the beginning** of the interaction | [Taft Law](https://www.taftlaw.com/news-events/law-bulletins/the-big-long-list-of-u-s-ai-laws-2/) |
| CA SB 1111 (2026) extends likeness law to digital voice replicas | [California AI laws](https://en.wikipedia.org/wiki/California_AI_laws) |
| CA SB 243 opens a private right of action where AI feels human | [Nat'l Law Review](https://natlawreview.com/article/when-ai-feels-human-californias-sb-243-opens-door-private-lawsuits) |

The last one deserves a second look. Sophia is engineered specifically to feel
human — vocal fry, uptalk, backchannel, breath injection, a fabricated
Stockton biography. That is the product's core value **and** the exact
characteristic a new California statute attaches liability to. Worth raising
with the attorney in the same conversation as everything else.

### Performance benchmarks

| Metric | Industry target | This system |
|---|---|---|
| Response gap felt as natural | 500–1,200 ms | Target 800 ms — **well chosen** |
| P50 end-to-end | < 1.5 s | Not measured |
| P95 end-to-end | < 5 s | Not measured |
| STT | < 200 ms | Not measured |
| LLM time-to-first-token | < 400 ms | Not measured |
| TTS time-to-first-byte | < 150 ms | Not measured |
| False endpoint rate | Tracked alongside latency | Not measured |
| Interruption cutoff latency | Tracked | Not measured |

Sources: [Hamming AI](https://hamming.ai/resources/voice-agent-evaluation-metrics-guide),
[Cekura](https://www.cekura.ai/blogs/voice-ai-latency-guide),
[Telnyx](https://telnyx.com/resources/voice-ai-agents-compared-latency).

The 800 ms target sits correctly inside the natural window — under 500 ms
starts to feel interruptive, over 1,500 ms feels inattentive. Somebody chose
that number well. The gap is measurement: per-call logging cannot show you the
p99 that produces your worst calls, and tail latency is what sellers remember.

**Practical implication:** `voice/simulator.py` already exists. Wiring it to
emit p50/p95/p99 plus false-endpoint rate is perhaps a day of work and turns
"does Sophia sound good" from an opinion into a number.

---

## 5. New plans — what I would actually do

### Plan A — "Legal first, inbound first" · recommended

The premise: the cheapest possible way to learn whether this business works is
to stop betting on the riskiest channel.

**Week 1 — one phone call and seven fixes**

1. **Retain a TCPA attorney for one consultation.** Three questions: (a) does
   AI-voice outbound to scraped property owners require prior express written
   consent; (b) does real-time transcription without audio retention trigger
   CA §632; (c) does SB 243 attach to a persona engineered to feel human.
   Cost: a few hundred to low four figures. It gates everything else.
2. In parallel, **Gate 2.5** from `REBUILD_MAP.md` — DNC fails closed,
   recipient-timezone hours, authenticate ingest, config layer, populate
   `.env.example`. None depend on the lawyer's answer.

**Week 2 — close the security hole**

3. Webhook signature verification (9.17).
4. Auth on the 28 endpoints (9.18).
5. Rate limiting.

**Week 3 — make the AI disclosure real**

6. Move disclosure to the **opening line**, unconditional, outside the model
   (9.19, 9.25). Not a prompt instruction — a deterministic first utterance.
7. Split `runtime_instruction` into a priority queue so a DNC kill switch
   cannot be clobbered by a tone nudge.

**Week 4 — one real conversation**

8. Point `/sell` at a landing page. Any traffic source. When a seller submits
   the form, they have initiated contact and consented — the cleanest legal
   position available.
9. **Sophia calls that one seller back.** Everything already built works on
   that call.

That is a live system with a real conversation inside a month, on the safest
legal footing, without resolving a single architectural question.

### Plan B — "Fix the queue" · one day, highest ratio

Independent of everything above, and roughly a day of work:

1. Merge `Sophia-Agent/bob/prioritizer.py` into the trunk.
2. Make `get_leads_for_outbound` sort by
   `(waiting_on_human, priority_callback, composite_score)`.
3. Add `.limit()`.
4. Claim the lead at selection time, not at outcome time (9.20).

Right now the system's single most valuable signal — a seller who asked to be
called back — is discarded. Fixing that costs a day and changes what the system
actually does.

### Plan C — "Instrument before optimizing"

Before another conversation module gets written:

1. Wire `voice/simulator.py` to emit p50/p95/p99 and false-endpoint rate.
2. Persist per-call cost (STT + LLM + TTS + telephony minutes).
3. Put both on the `/health` dashboard.

Then "is Sophia good" and "can we afford this" become measurements instead of
opinions. Currently neither can be answered at all.

### Plan D — "Delete before you build"

The rebuild map is 150 items. Some of that is work; some is deletion.

- Archive `bob-intelligence-` after §8.1 of the map harvests it.
- Delete the two trunk Bob copies that lose.
- Delete `scout/deduper.py` (0 bytes) and `sophia_legacy_runtime.md`.
- Delete the two test files importing modules that do not exist, or write the
  modules. Do not leave a suite that cannot collect.
- Pin every version in `requirements.txt`; drop `tenacity` and
  `livekit-agents` unless they get wired.

Cheap, and it makes everything after it legible.

### What I would explicitly *not* do next

- **Not the monorepo migration.** It is the largest item and it changes nothing
  a seller experiences.
- **Not Karpathys hardening.** Gate 3 is real work but it protects a governance
  layer nothing currently depends on.
- **Not more conversation modules.** There are eleven and none has faced a real
  seller. A twelfth is a guess stacked on eleven guesses.

---

## 6. Everything, ranked by (damage × likelihood) ÷ effort

| # | Item | Damage | Fix | Do |
|---|---|---|---|---|
| 1 | AI-voice consent standard (§2) | Business-ending | One consult | **Now** |
| 2 | DNC fails open (9.1) | Legal, per call | Hours | **Now** |
| 3 | Calling hours wrong timezone (9.2) | Legal, per call | 1 day | **Now** |
| 4 | No auth anywhere (9.3, 9.17, 9.18) | Total compromise | ~1 week | **Now** |
| 5 | AI disclosure reactive + model-discretionary (§2) | Legal, CA | 1 day | **Now** |
| 6 | Hot leads ignored by the queue (9.16) | Every hot lead lost | 1 day | **Now** |
| 7 | Safety instructions clobbered (9.19) | Kill switch can vanish | 1 day | **Now** |
| 8 | No recording disclosure (§2) | Legal, CA | Ask the lawyer | **Now** |
| 9 | Double-dialing race (9.20) | Seller experience + TCPA | 1 day | Next |
| 10 | Config layer / empty `.env.example` (9.6) | Silent misconfiguration | 1 day | Next |
| 11 | Events lost silently (9.7) | Invisible drift | Outbox, ~1 week | Next |
| 12 | Cannot scale past one replica (9.22) | Breaks when you grow | Redis, ~1 week | Next |
| 13 | Money units broken (9.9) | Flag always fires | Hours | Next |
| 14 | Test suite red (9.12) | Cannot trust changes | Days | Next |
| 15 | No cost tracking (9.24) | Unit economics unknown | 2 days | Next |
| 16 | No latency percentiles (9.27) | Cannot tell good from bad | 1 day | Next |
| 17 | `DEAD` sets `opted_out` (9.8) | Burns re-marketable leads | Hours | Soon |
| 18 | Unpinned dependencies (9.13) | Irreproducible builds | Hours | Soon |
| 19 | Schedulers in the web process (9.14) | Duplicate jobs on scale | 1 day | Soon |
| 20 | Unbounded queries (9.23) | Fails at volume | 1 day | Soon |
| 21 | Lost-update races (9.21) | Undercounted attempts | Hours | Soon |
| 22 | No retries on external APIs (9.25) | Transient failures fatal | 1 day | Soon |
| 23 | Webhook idempotency (9.29) | Corrupt call state | Hours | Soon |
| 24 | Triplicated Bob (map §8.1) | Duplicate truth | ~1 week | Rebuild |
| 25 | Triplicated Sophia (map §8.2) | Duplicate truth | ~2 weeks | Rebuild |
| 26 | Two ingest services (9.4) | Unknown system of record | Hours to determine | Rebuild |
| 27 | Karpathys fails open (9.5) | Auth silently off | Hours | Rebuild |
| 28 | 246 broad excepts (9.26) | Failures accumulate | Ongoing | Rebuild |
| 29 | Missing modules (9.10) | Suite cannot collect | Hours | Cleanup |
| 30 | Write-only fields (9.30) | Dead columns | Hours | Cleanup |
| 31 | Eviction scraper legality (9.11) | Unknown | Ask the lawyer | Cleanup |
| 32 | Comments / naming / rule drift (9.15) | Erosion | Ongoing | Cleanup |

**Items 1–8 are roughly two weeks and one phone call.** They are the difference
between a system that is dangerous to run and one that is merely unfinished.

---

## 7. The honest summary

**What is genuinely good:** the conversation engineering, the checkbox ladder,
the `CallBrief` contract, the scoring weights, the fair-housing filter, the
prompt-injection delimiting, the absence of any injection or deserialization
vulnerability, the 800 ms latency target, and documentation that is more candid
than most companies produce.

**What is genuinely bad:** no authentication of any kind, a DNC check that
fails open, calling hours in the wrong timezone, an AI disclosure that only
fires if asked and then asks a language model to please comply, a safety
channel that overwrites itself, hot leads that go nowhere, a test suite that
cannot collect, and a system that silently cannot run on more than one machine.

**What is uncertain and matters most:** whether the core business motion —
AI-voice cold calls to scraped property owners — is lawful without written
consent. Research says probably not. One attorney consultation settles it, and
nothing else on this list should be sequenced ahead of that call.

**The pattern across all thirty defects:** every one of them lives at a seam.
Something writes and nothing reads. Something is checked and the check fails
open. Something is measured and never aggregated. A dependency is installed and
never wired. The components are better than the connections between them, and
that is the single most useful thing to know about this codebase.

**And still, the largest fact:** twenty thousand lines, four architecture
documents, thirty known defects, one hundred and fifty planned work items — and
zero conversations with a real human being. Every estimate in this project
remains a guess until that changes.

---

*Thirty defects logged across this document and `MASTER_REFERENCE.md` §9. All
reproducible from the file and line given. Research sources linked inline.*
