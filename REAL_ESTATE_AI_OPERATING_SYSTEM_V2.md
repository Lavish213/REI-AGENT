# Real Estate AI Operating System — V2 Constitution

**Status:** proposed — not yet ratified. Sections marked **[OPEN]** need an
explicit decision before this is locked.

**Scope:** governs four repositories — `REI-AGENT` (integrated Bob +
Sophia service), `The-Dashboard` (Karpathys), `Sophia-Agent` (Sophia V1),
`bob-intelligence-` (standalone Bob).

**Home:** this document lives in `REI-AGENT`. If the monorepo decision in
§18[A] moves the authority layer, it moves with it.

Once ratified, this document wins. Where code disagrees with this document,
the code is wrong. Changes to this document are themselves consequential
decisions and require the same human authority as any other.

---

## 0. The guiding rule

> **Karpathys knows what is true and what is allowed.**
> **Bob decides what business strategy makes sense.**
> **Sophia decides how to conduct the conversation.**
> **Humans retain authority over consequential decisions.**

Every rule below is a consequence of that sentence. If a proposed change
cannot be justified from it, it does not belong.

### The three failure modes this exists to prevent

1. **Duplicate truth** — two systems each believing they own a fact, and
   silently disagreeing.
2. **Unsafe autonomy** — an AI taking a consequential action no human
   authorized and no ledger recorded.
3. **Invisible drift** — behaviour changing without anyone able to say when,
   why, or on whose authority.

---

## 1. Where we actually are

Ground truth as of 2026-09-06, read off the repositories themselves, not
aspiration.

There are **four** repositories, not three. The fourth one changes the plan.

| Repo | State | Real assets | Real problems |
|---|---|---|---|
| **REI-AGENT** | ~19,800 LOC backend, 137 Python files, 257 tests, 13 migrations, last commit 2026-06-08 | Already an integrated Bob + Sophia service: `backend/contracts/` (typed `CallBrief`, `IntelPacket`), `backend/bob/` (call_planner, decisions, events), `backend/voice/` (processors, states, prompts), `backend/karpathys/` (HTTP client, emitter, events), `backend/workflows/engine.py`, `backend/evals/` (cases, runner, report), `backend/compliance/`, `backend/scout/`, `backend/comps/` | Events to Karpathys are fire-and-forget and swallow their own exceptions — no outbox, no idempotency, no replay. Sophia still holds CRM truth. Governance/approval layer absent. No live call ever placed |
| **Karpathys** (`The-Dashboard`) | ~670 files, 28 test files, last commit 2026-05-30, phase 15 of 16 — "Hardening" never started | `governance/` (18 modules), `approvals/`, `events/` (dispatcher, replay, idempotency, store), `security/` (auth, rbac, permissions), models for `ai_decision`, `ai_execution`, `approval`, `audit_log`, `domain_event`, `context_snapshot`; a `sophia_bridge.py` route already exists | Untested relative to size. Authorization, actor integrity, fail-open governance, approval races, webhook auth, event ordering, resource scoping all unverified. Nothing on the REI-AGENT side verifies it received anything |
| **Sophia** (`Sophia-Agent`) | ~5,900 LOC, 426 tests, 10 migrations, 4 processes, 45 commits | Working voice pipeline, compliance engine (recipient-timezone TCPA, DNC, opt-out), voicemail/AMD, canonical `scout/intake.py`, `scout/validate.py`, dispo, worker heartbeats, `bob/prioritizer.py` | Holds its own CRM truth. Takes direct external side effects. Overlaps REI-AGENT almost entirely but is not the same code |
| **Bob** (`bob-intelligence-`) | 21 files, last commit 2026-06-08 | `call_planner/`, `events/`, `decisions/`, `scoring/`, `contracts/` | Third copy of the same modules. No consumer |

### The duplicate-truth problem is already live, and it is worse than three-way

Bob's call planner exists in **three** repositories, and all three copies
have diverged from each other:

| Module | REI-AGENT | Sophia-Agent | bob-intelligence- | Agreement |
|---|---|---|---|---|
| `brief_generator.py` | 58 lines | 136 lines | 141 lines | none — all three differ |
| `objective_selector.py` | 30 lines | 27 lines | 27 lines | none — all three differ |
| `checkbox_selector.py` | 40 lines | 39 lines | 42 lines | none — all three differ |

Three systems each believe they know how to plan a call, and they disagree.
That is failure mode #1 from §0, in production code, today. No amount of
architecture downstream survives this. **Exactly one Bob survives Gate 2.**

### What REI-AGENT already gets right

It is worth being explicit, because it changes what the rebuild is:

- **Bob → Sophia already runs over a typed contract.** `backend/contracts/call_brief.py`
  defines `CallBrief` with a closed `Phase` enum, a `MissingBox` enum, and
  explicit `to_dict`/`from_dict`. §9's StrategyPlan is an evolution of this,
  not a replacement for it.
- **Karpathys is already a remote service, not a shared library.**
  `backend/karpathys/client.py` posts to `KARPATHYS_URL/api/v1/ingest/*`
  with a shared secret and bounded retries. The service boundary in §3 is
  half-built already.
- **Sophia's cognition is already layered.** `backend/voice/processors/`
  and `backend/voice/states/` exist as separate concerns.

### What REI-AGENT gets wrong in a way that matters

`backend/karpathys/emitter.py` wraps every emit in `try/except` and logs the
exception. If Karpathys is down, slow, or misconfigured, the call proceeds
and the event is **gone**. There is no outbox, no retry beyond two immediate
attempts, no dead-letter, and nothing on either side that would notice.

This is failure mode #3 — invisible drift — with the mechanism already
installed. §6's transactional outbox is not a nice-to-have; it is the fix
for a live defect.

---

## 2. Authority model

Authority means: **the right to decide a fact is true, or that an action is
permitted.** Not merely storing it.

| Domain | Authority | Everyone else |
|---|---|---|
| Identity of people, properties, leads, deals | **Karpathys** | reads by ID |
| Whether contact is permitted | **Karpathys** | must ask, may not infer |
| What happened (the event log) | **Karpathys** | appends, never edits |
| Approval state of a consequential action | **Karpathys** | must wait |
| Seller facts and their provenance | **Karpathys** | proposes facts, never asserts |
| Business strategy for a deal | **Bob** | consumes as a snapshot |
| Valuation and its uncertainty | **Bob** | consumes with the uncertainty attached |
| Negotiation plan | **Bob** | Sophia executes within it |
| How a live conversation is conducted | **Sophia** | nobody overrides mid-turn |
| What was said, verbatim | **Sophia** | reports up, never re-interprets |
| Who is contacted, when, by what channel | **Communication Orchestrator** | requests, does not send |
| Whether a behaviour is good | **Evaluation** | advisory only, never blocking in prod |

### Authority rules

1. **One writer per fact.** If two systems can write the same field, one of
   them is wrong. Resolve at design time, never at runtime.
2. **Non-authorities propose, they do not assert.** Sophia does not "know"
   a seller's timeline; she *observed a claim* and submits it with
   provenance. Karpathys decides whether it becomes a fact.
3. **Authority is not transitive.** Karpathys owning truth does not make it
   competent to plan a call. It stores Bob's plan; it does not second-guess
   it.
4. **Reads are cheap, writes are governed.** Any system may read anything it
   is scoped to. Writes cross a boundary only through a defined command.

---

## 3. Service boundaries

```
┌──────────────────────────────────────────────────────────────┐
│                        KARPATHYS                             │
│  authority · workflows · governance · memory · audit         │
│                                                              │
│  ┌────────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Entities  │ │ Event Log │ │ Approval │ │ Execution    │  │
│  │  + IDs     │ │ + Outbox  │ │ Engine   │ │ Ledger       │  │
│  └────────────┘ └───────────┘ └──────────┘ └──────────────┘  │
│  ┌────────────┐ ┌───────────┐ ┌──────────────────────────┐   │
│  │  Contact + │ │  Memory   │ │ Communication            │   │
│  │  Consent   │ │  Facts    │ │ Orchestrator             │   │
│  └────────────┘ └───────────┘ └──────────────────────────┘   │
└───────▲──────────────────▲───────────────────▲───────────────┘
        │ commands         │ commands          │ commands
        │ + events         │ + events          │ + events
   ┌────┴─────┐      ┌─────┴──────┐      ┌─────┴──────┐
   │   BOB    │      │   SOPHIA   │      │ EVALUATION │
   │ strategy │      │ conversat. │      │ replay ·   │
   │ underwr. │      │ realtime   │      │ grading    │
   └──────────┘      └────────────┘      └────────────┘
```

### Hard boundary rules

- **No shared database.** Bob and Sophia do not connect to Karpathys'
  database. They talk over a defined interface. *(This is the single most
  expensive rule here and the one most likely to be argued with. It is also
  the only thing that actually prevents duplicate truth.)*
- **No direct external side effects from Bob or Sophia.** No SignalWire
  call, no SMS, no email originates outside the Communication Orchestrator.
- **Sophia may hold ephemeral session state.** A live call needs local
  state. That state is not truth and does not survive the call except as
  submitted facts and events.
- **Every cross-boundary call carries an actor.** No anonymous internal
  traffic. See §14.

**[OPEN 3.1]** Transport between services: synchronous HTTP with an event
log, or a message bus? Recommendation: **HTTP commands + event log first**.
A bus adds operational surface you do not need at one operator and one
market, and the outbox (§6) already gives you async delivery guarantees.

---

## 4. Canonical entities and IDs

### Entities

| Entity | Owner | Identity | Notes |
|---|---|---|---|
| `Person` | Karpathys | `person_id` | A human. Not a lead, not a phone number. |
| `Property` | Karpathys | `property_id` | A parcel. APN where known. |
| `Lead` | Karpathys | `lead_id` | A `Person`'s relationship to a `Property`. |
| `Deal` | Karpathys | `deal_id` | A pursued transaction. Created when a lead becomes actionable, not before. |
| `Contact` | Karpathys | `contact_id` | A reachable endpoint — phone or email. **Not** a person. §7. |
| `Conversation` | Karpathys | `conversation_id` | One call or one message thread. |
| `Turn` | Sophia → Karpathys | `turn_id` | One exchange within a conversation. |
| `MemoryFact` | Karpathys | `fact_id` | An asserted truth with provenance. §8. |
| `StrategyPlan` | Bob → Karpathys | `strategy_id` | A versioned strategy product. §9. |
| `Execution` | Karpathys | `execution_id` | One attempt at a consequential action. §6. |
| `Approval` | Karpathys | `approval_id` | A human decision on an execution. |
| `CommunicationAttempt` | Karpathys | `attempt_id` | One try at reaching a Contact. §13. |
| `Appointment` | Karpathys | `appointment_id` | A committed meeting. |

### The Person / Lead / Contact split

This is the most important modelling decision in the document, and the
current systems get it wrong.

Today a "lead" conflates a person, a property, and a phone number. That
breaks in three ordinary situations:

- One person owns three properties → three leads, three separate call
  histories, three chances to call the same human twice in a day.
- A property has two owners → one lead, no way to record who you actually
  spoke to.
- A person changes their phone number → history splits, or the old number
  keeps getting dialled.

**The V2 model:**

```
Person ──┬── Contact (phone)     ← consent lives here
         ├── Contact (phone 2)
         └── Contact (email)

Person ──── Lead ──── Property   ← one per relationship

Lead ─────► Deal                 ← only when actionable
```

Consequences that must hold:
- **Contact frequency limits apply per `Person`, not per `Lead`.** Owning
  three properties does not earn someone three calls a day.
- **Opt-out applies per `Person` across every `Contact` they own**, unless
  channel-specific by law.
- **A `Deal` is not created at import.** Most leads never become deals.
  Creating one per lead makes "how many deals do we have" meaningless.

### ID rules

1. **UUIDs, generated by the owner.** No sequential IDs, no natural keys as
   primary keys.
2. **IDs are never reused, never recycled, never renumbered.**
3. **Every cross-system reference is by ID.** Never by phone number, never
   by address string. Those change.
4. **IDs appear in every event, every log line, every ledger row.**

---

## 5. Event model

The event log is the system's memory of what happened. If it is not in the
log, it did not happen.

### Envelope

Every event, without exception:

```json
{
  "event_id":        "uuid",
  "event_type":      "lead.contacted",
  "event_version":   2,
  "occurred_at":     "2026-09-06T18:22:04.113Z",
  "recorded_at":     "2026-09-06T18:22:04.198Z",
  "actor": {
    "type":          "ai | human | system",
    "id":            "sophia | person_id | dialer",
    "on_behalf_of":  "person_id | null"
  },
  "subject": {
    "type":          "lead",
    "id":            "lead_id"
  },
  "correlation_id":  "uuid",
  "causation_id":    "event_id of what caused this",
  "idempotency_key": "string",
  "payload":         { }
}
```

**Why each field earns its place:**

- `occurred_at` vs `recorded_at` — a call ends at one moment and is written
  at another. Conflating them makes replay lie.
- `actor` — §14 depends on this being non-optional and non-forgeable.
- `on_behalf_of` — an AI acting under a human's delegated authority must
  record whose.
- `causation_id` — lets you answer "what caused this call to happen" in one
  query instead of a forensic reconstruction.
- `event_version` — you *will* change payload shapes. Consumers must be
  able to refuse an unknown version rather than misread it.

### Ordering and transactions

1. **Events are appended in the same transaction as the state change they
   describe.** Not after. Not best-effort. This is the transactional outbox
   (§6) and it is non-negotiable — every "event didn't fire" bug traces to
   violating it.
2. **Ordering is guaranteed per `subject`, not globally.** Global ordering
   is expensive and nobody needs it.
3. **Events are immutable.** A wrong event is corrected by a compensating
   event, never by an edit.
4. **Consumers must be idempotent.** Assume at-least-once delivery forever.

### Versioning

- Additive changes → same version.
- Removing or re-meaning a field → new version.
- Consumers declare which versions they accept and **reject unknown
  versions loudly** rather than guessing.

---

## 6. Shared infrastructure

The four pieces everything else depends on. Built in Gate 4, before any
rebuild of Bob or Sophia.

### 6.1 Transactional outbox

State change and event emission commit together or not at all.

```
BEGIN
  UPDATE leads SET stage = 'contacted' WHERE id = ...
  INSERT INTO outbox (event_id, event_type, payload, ...) VALUES (...)
COMMIT
                    │
                    ▼
        relay publishes, marks sent, retries on failure
```

Solves: the lost-event problem, the double-write problem, and the "we
updated the row but the webhook never fired" problem in one mechanism.

### 6.2 Execution ledger + idempotency

**Every consequential action gets a ledger row before it is attempted.**

```
execution_id · action_type · requested_by · approved_by · idempotency_key
             · status (requested → approved → executing → succeeded/failed)
             · request_payload · result · attempted_at · completed_at
```

Rules:
- **Nothing consequential happens without a ledger row.** No row, no action.
- The `idempotency_key` is derived from the action's meaning, not from a
  timestamp — retrying the same intent must collapse to one execution.
- **A ledger row in `executing` that never completes is an incident**, not
  a shrug. Surface it.

*Consequential* means: places a call, sends a message, makes an offer,
commits money, changes a legal position, or contacts a human. Everything
else is not consequential and does not need this.

### 6.3 Contact permission ledger

See §7. Append-only, never mutated.

### 6.4 MemoryFacts with provenance

See §8.

---

## 7. Contact and consent

**This is the compliance backbone. Get it wrong and the business risk is
real money, not just bad UX.**

### The Contact model

```
Contact
  contact_id · person_id · channel (voice|sms|email) · value (E.164 | email)
            · verified · verified_at · line_type · source · created_at
```

- A `Contact` belongs to exactly one `Person`.
- The same `value` may not be attached to two active `Person`s. If it is,
  that is a data incident requiring resolution, not a merge.
- **Values are normalized at the boundary.** E.164 for phone, lowercased for
  email. *(Sophia V1 learned this the hard way — unnormalized CSV phones
  created a second lead for the same human.)*

### The permission ledger

Append-only. Never updated, never deleted.

```
permission_id · contact_id · channel · state (granted|revoked|suppressed)
              · basis (express_written | express_oral | inquiry | list_purchase | none)
              · evidence_ref · effective_at · expires_at · recorded_by
```

**Current permission is derived by folding the ledger, never stored as a
mutable flag.** A boolean `opted_out` column is exactly how V1 nearly
re-enabled outreach to someone who had replied STOP.

### The permission check

One function. Every channel. No exceptions, no bypass:

```
may_contact(contact_id, channel, purpose, at_time) → Allow | Deny(reason)
```

It must consider, and **fail closed** on any error:

1. Permission ledger state for that `contact_id` + channel
2. Internal DNC list
3. Litigator / TCPA-risk lists where available
4. Time-of-day **in the contact's own timezone** — not ours
5. Frequency caps **per Person**, per channel, per window
6. Quiet periods after an opt-out, a complaint, or a "not interested"
7. Deal-stage suppression (do not cold-pitch someone under contract)
8. Global freeze state (§14)

**[OPEN 7.1]** Frequency caps. Proposal: max 1 call + 1 text per Person per
day, max 3 calls per Person per week, 30-day quiet period after an explicit
"not interested". These are business judgements with legal exposure — they
need your sign-off, not mine.

### Standing rules

- **Consent is per Person per channel**, and revocation is immediate and
  total across that channel.
- **Revocation never expires.** Grants may.
- **"Take me off your list" is a revocation** regardless of wording. It does
  not require the word STOP.
- **Contacting a listed property's owner directly is prohibited** while an
  exclusive listing is active — route to the listing agent. *(California
  tortious interference; carried forward from Sophia V1.)*

---

## 8. Memory authority

### What a MemoryFact is

```
fact_id · subject_type · subject_id · attribute · value · confidence
        · asserted_by (actor) · source_type · source_ref
        · observed_at · recorded_at · superseded_by · retracted_at
```

`source_type` is one of: `seller_stated`, `public_record`, `list_provider`,
`inferred`, `operator_entered`, `third_party_api`.

### Rules

1. **No fact without provenance.** A value with no `source_ref` is not a
   fact and is rejected at write time.
2. **Facts are never overwritten.** A new observation supersedes; the old
   row keeps `superseded_by`.
3. **Sophia and Bob propose facts. Karpathys asserts them.** A seller
   saying "the roof is fine" is a `seller_stated` observation, not truth.
4. **Confidence is required and must be honest.** Anything derived from a
   single unverified claim is low confidence forever, however often it is
   repeated.
5. **Retraction is explicit**, with a reason. Never a delete.
6. **Conflicting facts are a first-class state**, not an error. Two sources
   disagreeing about square footage is normal; picking one silently is not.

### Precedence when facts conflict

`public_record` > `operator_entered` > `third_party_api` > `seller_stated`
> `list_provider` > `inferred`

With one override: **a seller's statement about their own intent, timeline,
or motivation outranks everything.** Nobody else can know it.

**[OPEN 8.1]** Do seller statements about *physical condition* decay? A
seller saying "roof is fine" 8 months ago is weak evidence today.
Recommendation: confidence decays with age for `seller_stated` physical
facts, never for intent facts.

---

## 9. Bob — acquisition intelligence

Bob's job: **decide what business strategy makes sense.** He never talks to
anyone and never places a call.

### Layers

```
Market context ──► Pattern detection ──► Opportunity identification
      │                                          │
      ▼                                          ▼
 Lockout check ◄───────────────────────── Valuation + uncertainty
      │                                          │
      ▼                                          ▼
 Strategy matrix ──► Simulation ──► Negotiation plan ──► StrategyPlan
```

| Layer | Produces | Notes |
|---|---|---|
| **Market context** | comps, absorption, trend | Inputs, not conclusions |
| **Pattern detection** | distress signals, timing signals | |
| **Opportunity** | is this worth pursuing at all | Must be able to say **no** |
| **Lockout** | hard disqualifiers | Runs *before* expensive work |
| **Valuation** | ARV, MAO, **and uncertainty** | §11 |
| **Strategy matrix** | cash / creative / wholesale / pass | Multiple viable strategies is normal |
| **Simulation** | expected outcomes per strategy | |
| **Negotiation** | multi-issue plan, concession ladder | §10 |
| **StrategyPlan** | the versioned output | Immutable once published |

### The StrategyPlan contract

```
strategy_id · deal_id · version · created_at · valid_until
            · strategy_type · valuation {point, range, confidence}
            · walk_away · opening_position · concession_ladder
            · critical_unknowns[] · assumptions[]
            · invalidated_by[] · superseded_by
```

Rules:
- **Immutable once published.** Changes create a new version.
- **Carries its own invalidation conditions.** "This plan assumes the roof
  is intact; if that is false, this plan is void."
- **Material deal changes auto-invalidate.** Sophia may never act on a
  stale plan — she receives a snapshot with `valid_until` and must refuse
  to use an expired one.
- **`critical_unknowns` is the interface to Sophia's objectives.** Bob says
  which unanswered questions actually move the decision; Sophia decides how
  to ask.

**Value of information (later gate):** rank unknowns by how much resolving
them would change the decision, not by how much is unknown. An unknown that
cannot change the answer is not worth call time.

### Bob's hard constraints

- **Bob may not initiate contact.** Ever.
- **Bob may not assert facts** — only derive strategy from Karpathys' facts.
- **Bob must express uncertainty.** A point estimate with no range is a
  rejected output.
- **Bob must be able to recommend `pass`.** A strategy engine that always
  finds a strategy is a rationalization engine.

---

## 10. Negotiation model

Single-issue price haggling is what V1 does implicitly and it is the wrong
frame.

### Multi-issue

Real levers: **price · close timing · repairs · possession · certainty ·
fees · contingencies.** Sellers trade across these constantly — "I'll take
less if I can stay 30 days" is a better deal for both sides than either
side's opening price.

```
NegotiationPlan
  issues[]         each with: our_range, their_estimated_range, our_priority
  opening_position
  concession_ladder    what we give, in what order, for what in return
  walk_away            per issue and overall
  batna                what we do if this fails
```

### Rules

1. **Never concede without a trade.** Every concession names what it asks
   for.
2. **Walk-away is set before the conversation**, by Bob, and Sophia may not
   move it. A live agent under social pressure is exactly who should not be
   allowed to redefine the floor.
3. **The ladder is a plan, not a script.** Sophia decides how and whether to
   use each rung.
4. **Crossing walk-away is a governed action** requiring human approval.

**[OPEN 10.1]** Does Sophia have *any* authority to make a binding offer, or
does every number she says carry "subject to Alanzo confirming"?
Recommendation: **no binding authority in V2**, full stop. Revisit only
after months of clean call data.

---

## 11. Valuation uncertainty

**A point estimate is a lie with a confident face.**

```
Valuation
  point · range_low · range_high · confidence
        · method · comp_count · comp_quality
        · assumptions[] · critical_unknowns[]
        · computed_at · valid_until
```

### Rules

1. **Every valuation carries a range.** Bob emits no bare numbers.
2. **Confidence is driven by evidence quality**, not by model certainty —
   three stale distant comps produce a wide range regardless of how neatly
   the math converges.
3. **Sophia quotes ranges, never points**, and only when the range is tight
   enough to be useful. Below a confidence floor she says she needs someone
   to look at it.
4. **Unknowns that would move the range materially are surfaced as
   `critical_unknowns`** and become call objectives.
5. **Valuations expire.** A 90-day-old ARV in a moving market is not a fact.

---

## 12. Sophia — conversation runtime

Sophia's job: **decide how to conduct the conversation.** She does not
decide strategy and does not own truth.

### Cognition layers

```
Session
  └─ Turn Controller ────► interruption / backchannel handling
       └─ Seller State ──► microstates (defensive, curious, rushed, hostile…)
            └─ Conversation Health ──► is this going well, should it stop
                 └─ Objective Engine ──► what am I trying to learn right now
                      └─ Context Router ──► what does the model need to see
                           └─ Response Planner ──► what to say
                                └─ Spoken Renderer ──► how to say it
```

| Layer | Owns |
|---|---|
| **Session** | one call, its lifecycle, its IDs |
| **Turn Controller** | whose turn it is; barge-in vs backchannel |
| **Seller State** | durable read of the person across the call |
| **Microstates** | momentary shifts — a sigh, a hardening, a softening |
| **Conversation Health** | is this working; when to gracefully stop |
| **Objective Engine** | current objective, from Bob's `critical_unknowns` |
| **Context Router** | assembling only what this turn needs |
| **Response Planner** | content of the reply |
| **Spoken Renderer** | prosody, pacing, length — how it lands aloud |

### IDs Sophia must emit

`session_id` · `turn_id` · `response_id` · `speech_id` · `execution_id`

Every one appears in the event log. Without them, "she said something
strange 40 seconds in" is unanswerable.

### Deterministic STOP

Non-negotiable, and **must not depend on the model choosing to comply**:

| Trigger | Behaviour |
|---|---|
| "stop calling me" / "take me off your list" | Immediate wind-down, revoke, end |
| Request for a human | Stop qualifying, escalate, end warmly |
| Hostility or distress | Stop the pitch, offer to end |
| Legal or financial advice sought | Refuse, escalate |
| Governance freeze mid-call | Wind down at the next turn boundary |
| Health below floor | Graceful exit |

These are enforced **outside** the LLM. A prompt instruction is a
preference; this is a control.

### Sophia's hard constraints

- **No external side effects.** Every send goes through the Orchestrator.
- **No CRM truth.** Facts are submitted with provenance and forgotten.
- **No strategy invention.** If Bob's plan is missing or stale, she
  qualifies only and books nothing binding.
- **Never denies being AI.** *(FCC Feb 2024 — TCPA caller-identification.)*
- **Never states a fact not in her context.** Carried from V1 and load-bearing.

---

## 13. Communication orchestration

**One door for every outbound message and call.** Nothing else may send.

```
requester (Bob | Sophia | workflow | human)
        │  requests contact
        ▼
┌───────────────────────────────────────────┐
│        COMMUNICATION ORCHESTRATOR         │
│  1. may_contact() — fail closed           │
│  2. frequency + quiet-hours (per Person)  │
│  3. channel selection + fallback          │
│  4. execution ledger row                  │
│  5. governance check if consequential     │
│  6. dispatch to provider                  │
│  7. record CommunicationAttempt + event   │
└───────────────────────────────────────────┘
```

### Rules

1. **Requesters request; they never send.** The Orchestrator may refuse and
   the refusal is recorded with a reason.
2. **Every attempt is recorded** — including refused ones. "Why didn't we
   call them" must be answerable.
3. **Channel choice is orchestration, not strategy.** Bob says "reach this
   person about X"; the Orchestrator decides call vs text vs email based on
   permission, history, and time.
4. **Cadence lives here, not in workers.** V1's dialer contained cadence
   logic; that spreads policy across processes.
5. **Kill switch.** One setting halts all outbound immediately without a
   deploy. *(V1 has this via `MAX_CONCURRENT_OUTBOUND=0`; V2 makes it
   first-class and global.)*

---

## 14. Governance and human authority

### Actor integrity

- **Every request carries an authenticated actor.** No anonymous internal
  calls, including service-to-service.
- **Actors are not self-asserted.** A service claiming `actor: human` in a
  payload is not evidence. Identity comes from the authenticated channel.
- **AI actors are always distinguishable from humans** in the log. Always.
- **Delegated authority is explicit and bounded** — scope, expiry, and the
  delegating human recorded.

### Fail-closed

**Every governance decision fails closed.** If the engine errors, is
unreachable, or returns something unparseable, the answer is **deny**.

This is the single most important line in this document. A governance
system that fails open is worse than none, because it produces confidence
without protection.

### Approvals

- **Approval state transitions are atomic.** Compare-and-set on the
  execution row. *(Approval races were named as a known Karpathys defect —
  two approvers, or an approve/expire collision, must not both win.)*
- **Approvals are scoped** to one execution, not "this kind of thing".
- **Approvals expire.** An unactioned approval is not permission a week later.
- **Self-approval is prohibited** where the requester is the approver.

### What always requires a human

- Making or accepting a binding offer
- Any commitment of money
- Crossing a walk-away
- Contacting anyone outside normal permission rules
- Changing governance policy itself
- Ratifying or amending this document

**[OPEN 14.1]** Quorum. Karpathys has a `quorum.py`. With one operator,
quorum is theatre. Recommendation: single-approver now, structure retained
so it can tighten when there is a second human.

### Freeze

A global freeze halts all AI-initiated action immediately. Live calls wind
down at the next turn boundary rather than dropping — hanging up on a
seller mid-sentence is its own harm.

---

## 15. Evaluation

Advisory. **Never in the production decision path.**

| Capability | Purpose |
|---|---|
| **Replay** | Reconstruct any call or decision from the event log |
| **Transcript grading** | Rubric scoring of real conversations |
| **Simulated sellers** | Personas for regression |
| **Adversarial scenarios** | Hostile, confused, litigious, scripted-scam-aware |
| **Shadow Sophia** | New version runs alongside, output compared, never spoken |
| **Shadow Bob** | New strategy engine scored against the live one |
| **Outcome analysis** | What actually correlated with contracts |
| **Process mining** | Real paths through the event log vs the designed ones |

### Rules

1. **Evaluation never blocks a live call.** It reads the log; it does not
   sit in the path.
2. **Grading is versioned.** A score is meaningless without the rubric
   version that produced it.
3. **Replay must be faithful.** If replaying an event stream does not
   reproduce the decision, either the log is lossy or the decision was
   non-deterministic. Both are bugs.
4. **Shadow before canary, always.**

---

## 16. The gates

Nothing in a later gate starts before the earlier one has a passing test
suite. This is the entire discipline.

| Gate | Deliverable | Done when |
|---|---|---|
| **1** | This document, ratified | All **[OPEN]** items decided |
| **2** | Rebuild map — every file `KEEP`/`HARDEN`/`MOVE`/`ADAPT`/`REPLACE`/`DELETE`/`LEGACY`, with an exact `0/N` checklist | Every file in all four repos classified. **Triplicate Bob resolved, losing copies deleted.** |
| **3** | Karpathys hardened | Authorization, actor integrity, fail-closed governance, atomic approvals, webhook auth, event ordering, resource scoping — each with tests |
| **4** | Shared infrastructure | Outbox, event envelope, execution ledger, Contact + permission ledger, CommunicationAttempt, Appointment, MemoryFacts — all tested |
| **5** | Sophia Runtime V2 | New cognition center, all IDs emitted, deterministic STOP proven under test |
| **6** | Sophia wired through Karpathys | Zero independent CRM writes, zero direct side effects |
| **7** | Bob V2 | Full layer stack, uncertainty everywhere, critical unknowns, multi-issue negotiation |
| **8** | Bob ↔ Karpathys ↔ Sophia | Strategy snapshots, automatic invalidation, no stale-plan execution possible |
| **9** | Learning layer | Replay faithful, grading versioned, shadow modes running |
| **10** | Controlled real calls | Internal → known testers → adversarial → shadow → canary → graduated autonomy |

### On Gate 10

Autonomy is earned per capability, not granted wholesale:

```
inbound only ──► outbound to testers ──► outbound with human approval per call
             ──► autonomous within tight caps ──► graduated caps
```

**Autonomous outbound is last.** Not because the code is unready — because
the *evidence* that it behaves well does not exist until the earlier stages
produce it.

---

## 17. Invariants

Violating any of these is a defect regardless of what a test says.

1. One writer per fact.
2. No consequential action without an execution-ledger row.
3. No outbound communication outside the Orchestrator.
4. No contact without a passing `may_contact` check.
5. Governance failures deny.
6. Every event carries an authenticated actor.
7. Events are immutable; corrections are compensating events.
8. State changes and their events commit in one transaction.
9. No fact without provenance.
10. No valuation without a range.
11. Sophia never acts on an expired strategy.
12. STOP conditions are enforced outside the model.
13. Consent revocation is immediate, total, and permanent.
14. AI actors are always distinguishable from humans in the log.
15. Evaluation never sits in the production decision path.

---

## 18. Open decisions

These need **your** call. I have given a recommendation for each; none are
locked until you say so.

| # | Decision | Recommendation |
|---|---|---|
| **3.1** | Service transport — HTTP + event log, or message bus | HTTP + outbox first; bus only if scale demands |
| **7.1** | Frequency caps per Person | 1 call + 1 text/day, 3 calls/week, 30-day quiet after "not interested" |
| **8.1** | Do seller-stated physical facts decay? | Yes for condition, never for intent |
| **10.1** | May Sophia make a binding offer? | No, not in V2 |
| **14.1** | Approval quorum with one operator | Single approver, structure retained |
| **A** | Monorepo or separate repos? | **Recommend monorepo — `REI-AGENT` already is one; see below** |
| **B** | Does `Sophia-Agent` V1 keep running during the rebuild? | Recommend yes, frozen, as the fallback and as the source of the compliance/intake modules |
| **C** | Which of the three Bobs survives? | `REI-AGENT/backend/bob/` as the home, merged forward with Sophia-Agent's `prioritizer.py` and fixed ladder; `bob-intelligence-` archived |

### On (A), monorepo

This was open when the ground truth was three repos. It is close to settled
now, because `REI-AGENT` **is already the monorepo** — Bob, Sophia, scout,
comps, compliance, workflows, evals, and the Karpathys client all live in
one Python package with one test suite, and Karpathys stays a separate
service reached over HTTP.

The recommendation is therefore to ratify what exists: **one repository for
Bob + Sophia + orchestration, with enforced module boundaries; Karpathys
remains a separate deployable with no shared database.** Boundary violations
then show up in review instead of in production.

What still needs your explicit call is not the shape but the **direction of
the merge**: `REI-AGENT` is the integration and has the typed contracts, but
`Sophia-Agent` has the compliance engine, canonical intake, validation,
voicemail/AMD, dispo, heartbeats, and 426 tests that `REI-AGENT` does not.

Recommendation: **`REI-AGENT` is the trunk; `Sophia-Agent` modules are
merged into it**, module by module, with its tests. Gate 2 produces the
per-file list.

### On (C), the three Bobs

Do not pick a winner by repo. Pick per module, because the divergence is not
a clean fork — `REI-AGENT`'s `brief_generator.py` is 58 lines against
Sophia-Agent's 136 and bob-intelligence-'s 141, and the short one is not
simply an older version. Gate 2 must diff all three copies of all five
`call_planner` modules and record, per module, which body survives and why.
The two losing copies are deleted in the same commit, not left in place.

---

## 19. What this document deliberately does not do

- **It does not design database schemas.** Entities and ownership, yes.
  Column types belong in Gate 4.
- **It does not choose libraries**, beyond what already exists and works.
- **It does not specify the LLM prompt.** That is Sophia's internal
  business and will change weekly.
- **It does not promise the rebuild is worth it.** Sophia V1 works, is
  tested, and has never made a call. If the honest goal is revenue this
  quarter, the shortest path is to place a live call with V1 and learn
  something real — then rebuild with that knowledge. This document is the
  right plan for a durable system; it is not the fastest path to a first
  contract, and those are different goals.

---

*Ratification: this document takes effect when the [OPEN] items in §18 are
decided and recorded here. Until then it is a proposal.*
