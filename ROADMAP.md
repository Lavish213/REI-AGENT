# Roadmap — Everything Left

Full direction from here to safe operation. Written 2026-09-11.

**Companion docs:** `MASTER_REFERENCE.md` (what exists) · `AUDIT_AND_GRADE.md`
(grade + 30 defects) · `SECOND_AUDIT_VERIFICATION.md` (68-finding register) ·
`EMERGENCY_CONTAINMENT.md` (what landed) · `REBUILD_MAP.md` (file-by-file) ·
`PII_PURGE_RUNBOOK.md`.

**Current state: outbound disabled. Gate 1A in progress, steps 1–3 landed.**

---

## 0. The sequence

```
✅ emergency four
🔄 Gate 1A    tenant · STOP path · adversarial tests · external verification
⬜ Gate 1     trusted ingress
⬜ Gate 2     permission ledger
⬜ Gate 3     reproducible schema
⬜ Gate 4     durable job execution
⬜ Gate 5     data governance
⬜ Gate 6     internal voice
⬜ Gate 7     seller pilot
```

Nothing starts before the previous gate has an evidence bundle: commit, test
run, deployment proof, configuration export, owner approval, rollback result,
and the list of risks still open.

---

## Gate 1A — capability security

### Step 1 — Persist tenant ownership · **landed**

`supabase/migrations/20260911_tenant_and_suppression.sql`

- `tenants` table; one row seeded, uuid `…0001`, slug `san-joaquin-house-buyers`.
- `tenant_id` added to 29 business tables, backfilled, `NOT NULL`, defaulted, FK
  to `tenants`, indexed.
- RLS enabled per table with a `current_setting('app.tenant_id')` isolation policy.
- Hard deny in `execution_context._resolve_tenant`: unconfigured `TENANT_ID`
  denies, lead tenant mismatch denies, **lead with no tenant now denies** — the
  single-tenant adoption allowance is removed.

**Two things you must do before this migration is real:**

1. **Confirm the database has one operator's data only.** The backfill assigns
   every existing row to one tenant. If it ever held more, stop.
2. **Set `TENANT_ID=00000000-0000-0000-0000-000000000001`** in Railway and
   Vercel. Without it every tool call denies — by design, but it will look like
   an outage.

**Known limit:** the app connects with the Supabase **service key, which
bypasses RLS.** These policies protect the dashboard's anon path and give
defence in depth; they are not yet the enforcement boundary. Setting
`app.tenant_id` per request, or moving off the service key, is Gate 1 work.

**Also unfinished:** only 6 of 28 tables have committed definitions, so this
migration `ALTER`s tables it cannot see. The `RAISE NOTICE` on a missing table
is deliberate — run it and **read the notices**, they tell you which tables the
live database does not have.

### Step 2 — Dedicated STOP/DNC path · **landed**

New tool `honor_stop_request`:

| Property | Behaviour |
|---|---|
| Arguments | `verbatim` (required), `channel` (optional enum). **No identity fields.** |
| Contact | Derived from the active call via `ResolvedContext`. Model cannot supply it. |
| Effect | Suppression **only** — evidence row, DNC entry, lead flag. Never grants, never clears. |
| Evidence | `suppression_events`, append-only, `UPDATE`/`DELETE` revoked from `PUBLIC`. |
| Ends call | Sets `stop_requested` and `call_should_end`. |
| Availability | Unconditional. Works with no packet, in fallback mode, and with outbound disabled. |
| Total write failure | Call still ends; `logger.critical("STOP_REQUEST_UNPERSISTED")` names the contact for manual suppression. |

**`set_disposition` is now gated**, which resolves the deviation flagged in
`EMERGENCY_CONTAINMENT.md` §3 — it was only unconditional because the DNC path
depended on it, and that path now has its own primitive.

**Post-STOP lockout:** `execute_tool` denies every tool except `end_call` once
`stop_requested` is set. The referral ask cannot run after a stop request.

**Prompt updated.** A tool nothing invokes is the defect pattern this project
keeps producing, so `sophia_runtime.md` now carries a STOP section: call it
immediately, never ask why, never ask for a referral, never set a disposition
first, say nothing after.

**Defect 69, found while building this:** `ComplianceEngine().handle_opt_out()`
was called at `email_webhook.py:158` and **the method did not exist.** The
`AttributeError` was swallowed by the surrounding `try/except`, so every email
spam-report opt-out silently failed to record. Implemented, and it now writes
evidence through the same ledger.

### Step 3 — Adversarial tests · **landed**

`tests/test_tool_containment.py` — **58 passing.**

| Requirement | Covered by |
|---|---|
| Missing / mismatched tenant | `TestTenantBoundary` — 8 tests |
| Replaced lead ID, phone, email, address | `TestIdentitySubstitution` — 6 tests |
| Missing / malformed permissions | `TestFailClosed` — 9 tests |
| Replayed tool requests | `TestReplayAndDegradedOperation` — 3 tests |
| STOP during degraded operation | `TestStopRequest` — no packet, fallback mode, outbound off |
| No action after STOP | `test_no_action_occurs_after_stop` iterates every side-effect tool |
| Prompt injection | `TestPromptInjection` — 2 tests |
| Cross-call reuse | `TestCrossCallReuse` — 3 tests |

Full suite **76 failed / 210 passed**, up from 143/83 at session start. All
remaining failures pre-existing: `pipecat` ×42, `anthropic` ×15, `fastapi` ×10,
the missing `spoken_renderer`/`emotion` modules, the cents/dollars bug.

### Step 4 — Verify containment outside Git · **yours, cannot be done from here**

Everything above is source control. None of it proves the deployed system is
contained. This checklist needs a human with console access.

| # | Check | Where | Pass condition |
|---|---|---|---|
| 4.1 | `OUTBOUND_ENABLED` | Railway variables | Absent or not `true` |
| 4.2 | `TENANT_ID` | Railway + Vercel | Set to the seeded uuid |
| 4.3 | Deployed commit | Railway deploy log | Matches this branch head |
| 4.4 | Scheduler jobs | Railway logs, search `scheduler_started` | Six jobs; decide whether to stop them |
| 4.5 | Replica count | Railway | **Exactly 1** — see §9.22, in-memory call state |
| 4.6 | SignalWire voice webhook | SignalWire console | Points at the intended host |
| 4.7 | SignalWire campaigns | SignalWire console | No active outbound campaign |
| 4.8 | SignalWire recent activity | Call + message logs, 30 days | Account for every outbound leg |
| 4.9 | SignalWire charges | Billing | Reconcile against 4.8 |
| 4.10 | SendGrid activity | Activity feed, 30 days | No unexplained sends |
| 4.11 | Supabase `leads` sample | SQL editor | `tenant_id` populated after migration |
| 4.12 | Supabase RLS | Advisors | Note which tables lack policies |
| 4.13 | Anthropic / Deepgram / ElevenLabs usage | Provider dashboards | Reconcile spend against known tests |
| 4.14 | Dashboard ingest routes | `curl -X POST <vercel-url>/api/ingest/call -d '{}'` | **Should 401. Will 200.** See §9.3 |

**4.14 will fail.** That is finding 9.3 and it is Gate 1 work. Run it anyway so
you have the before-and-after.

**If 4.8 or 4.10 shows outbound you cannot account for, stop and treat it as an
incident**, not a bug: rotate keys, capture the logs, then look at code.

### Step 5 — Reconstruct the missing 22 tables

The migration in step 1 cannot verify what it alters. Before Gate 1:

1. Export the live schema:
   `pg_dump --schema-only --no-owner --no-privileges`
2. Split it into committed migrations that build an empty database to the same
   shape.
3. Build from scratch, diff against the export, explain every difference.
4. Add to CI so drift fails the build.

Until this passes, **no environment can be rebuilt from the repository** and no
rollback is safe.

---

## Gate 1 — Trusted ingress

Five workstreams. Nothing here is optional and none of it is started.

### 1.1 Authenticate all 81 routes

Classify first, because the answer differs per class:

| Class | Auth |
|---|---|
| Operator UI/API | Session or OAuth2 + JWT, short expiry, refresh |
| Provider callbacks | Signature verification only — never a session |
| Internal service | mTLS or signed service token |
| Public health | Unauthenticated, but no data in the response |
| Everything else | **Deny** |

Deny by default at the router, then allow explicitly. An allowlist you have to
opt into cannot silently miss a new route.

### 1.2 Role and tenant authorization

Authentication answers *who*. This answers *what may they touch*. Every handler
resolves a tenant from the authenticated principal — never from a request
parameter — and every query filters on it. Then set `app.tenant_id` per request
so the RLS policies from Gate 1A step 1 actually engage.

Test cross-tenant reads **and** writes at both the API and the database layer.
A passing API test with RLS off proves nothing.

### 1.3 Verify provider callbacks

- **SignalWire:** signature verification on `voice/webhook.py`,
  `voice/outbound_webhook.py`, `api/routes/sms.py`, `api/routes/sms_status.py`.
  Currently **zero** of the four verify anything.
- **SendGrid:** the Event Webhook uses **ECDSA public-key verification**, not a
  shared secret. `email_webhook.py`'s shared-secret approach is the wrong
  primitive, and it fails open besides.
- Reject unsigned requests. Do not log and continue.

### 1.4 Authenticate WebSockets

Media sockets currently accept any connection. Issue a short-lived single-use
token when the call is created; the socket presents it once; the server binds it
to that `call_sid` and burns it. Reject reuse. Expire in seconds, not minutes.

### 1.5 Replay protection, payload limits, rate limits

- Nonce or timestamp window on every signed callback; reject stale and reject
  repeats.
- Body size limits on all 28 POST endpoints. There are none today.
- Rate limits per tenant, per IP, per endpoint class.
- **Spend caps**, which are the version that actually stops a bad night:
  per-tenant daily ceilings on calls, messages, and model tokens, with a
  breaker that disables outbound automatically.

### Gate 1 exit

An external penetration test before any seller contact. Not a scan — a person.

---

## Gate 2 — Permission ledger

**Do not start until Gate 1 passes.**

The model: `callable` is deleted as an authorization signal. Reachability,
ownership confidence, source and last-verified become informational attributes.
Contact authority comes only from an immutable, append-only permission decision
naming channel, purpose, evidence, and expiry — checked immediately before every
send.

- Imports land `quarantined`; bulk activation creates review tasks, never
  contact authority.
- DNC is one mandatory **deny** source, never affirmative permission. Registry
  version no older than 31 days for the FTC safe harbour.
- Channel-specific suppression. An email unsubscribe suppresses email, not SMS
  (fixes N-H8), and `DEAD` stops meaning `opted_out` (fixes §9.8).
- `send_sms` stops being importable. All sends become durable intents carrying a
  permission-decision ID, executed by one worker (fixes N-H1).

**The attorney call gates this gate.** Under the Feb 2024 FCC ruling an AI voice
is an artificial voice, which likely requires prior express **written** consent
for telemarketing — and an established business relationship does not exempt it.
If that reading holds, the ledger's job is not to record permission you have but
to prove you may not call yet. Design it after you know the answer.

---

## Gate 3 — Reproducible schema

Gate 1A step 5, finished and enforced: complete migrations, CI build from
scratch, RLS coverage, FK and check constraints, job leases, idempotency keys,
retention columns, audit write restrictions. Plus the delivery basics this repo
has none of — CI workflow, pinned dependencies, SBOM, secret scanning, branch
protection.

---

## Gate 4 — Durable job execution

Every state change and its outbound effect commit in one transaction: domain
write plus an outbox row. A worker delivers the outbox and records the result.
Consumers dedupe on an inbox key.

- Claim jobs with `FOR UPDATE SKIP LOCKED` — fixes the double-dial race (§9.20).
- Callbacks become durable jobs; clear only after terminal processing (N-H6).
- Move the six APScheduler jobs out of the web process (§9.14).
- Replace in-memory `app.state.call_contexts` with shared state so more than one
  replica is possible (§9.22).
- Reconcile provider state against application state on a schedule.

Kill a worker before the provider request, after provider acceptance, and during
callback processing. **No injected failure may increase contact authority or
lose an acknowledged seller request.**

---

## Gate 5 — Data governance

Source register per connector: owner, licence, permitted purpose, provenance,
refresh, retention, deletion path, rate limit, robots/API policy. No connector
runs without one — that includes settling the eviction-scraper question (§9.11).

Vendor data-flow map: which fields reach Anthropic, Deepgram, Cartesia, Groq,
Together, ElevenLabs, Langfuse, Karpathys. No-training and retention controls
where available, PII minimisation, deletion propagation.

Plus retention schedules, backup and **tested** restore, and incident runbooks
for: leaked service key, forged callback, accidental outreach, DNC failure,
wrong offer, cross-tenant disclosure, runaway calls, compromised number.

And finish the PropWire history rewrite (`PII_PURGE_RUNBOOK.md`).

---

## Gate 6 — Internal voice

One pinned pipeline. Model, prompt, and tool-schema versions recorded per call.

Instrument first: p50/p95/p99 end-to-end, STT/LLM/TTS component latency, false
endpoint rate, interruption cutoff latency, per-call cost. Targets from the
research in `AUDIT_AND_GRADE.md` §4 — P50 under 1.5s, P95 under 5s, the 800ms
response target you already chose correctly.

Then adversarial conversation tests against internal numbers only: truthful
opening, AI disclosure unprompted and on request, wrong party, DNC mid-sentence,
language switch, minor answers, hostility, legal questions, background TV,
multiple speakers, voicemail, AMD uncertainty, disconnects.

**Score side effects, not just words.** A polite transcript with an unauthorised
SMS is a failed call.

Before this gate: move the AI disclosure **out of the prompt** into a
deterministic first utterance. It is still model-discretionary today.

---

## Gate 7 — Seller pilot

Legal, security, privacy and operations sign-off. Then graduated:

```
inbound only → outbound to consenting testers → per-call human approval
             → autonomous within tight caps → graduated caps
```

Defined stop thresholds — complaint rate, opt-out rate, carrier labelling — with
automatic disable.

---

## If you want revenue sooner

The whole roadmap is months. The inbound path is weeks, and nothing above
blocks it:

1. Gate 1A step 4 (verify containment) — a day.
2. Authenticate the dashboard ingest routes — hours.
3. Point `/sell` at a landing page. Any traffic source.
4. When a seller submits the form, **they initiated contact.** Cleanest legal
   position available.
5. Sophia calls that one seller back, with `OUTBOUND_ENABLED=true` scoped to
   consented leads only.

Everything already built works on that call. What changes is the top of the
funnel, not Sophia. **This system is safest doing the thing it has never tried.**

One real conversation will tell you more about what to build than any of these
six documents — including which of the 68 findings turn out not to matter.

---

## The immediate list

| # | Do | Who | Effort |
|---|---|---|---|
| 1 | Confirm single-operator data, then run the tenant migration | You | 1 hour |
| 2 | Set `TENANT_ID` in Railway and Vercel | You | 5 min |
| 3 | Gate 1A step 4 — the 14 external checks | You | 1 day |
| 4 | Book the TCPA attorney call | You | 1 call |
| 5 | Export live schema, reconstruct 22 missing tables | Engineering | 1 week |
| 6 | Gate 1 — authenticate 81 routes | Engineering | 2 weeks |
| 7 | Verify SignalWire + SendGrid callbacks | Engineering | 3 days |
| 8 | Purge PropWire from history | You + engineering | 1 day |

Items 1–4 are yours and none needs an engineer. **Item 4 can invalidate the
business model, so it should not wait behind item 5.**
