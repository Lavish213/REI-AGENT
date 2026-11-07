# Three-Repo Audit — Bob, Karpathys, and a Correction

**Date:** 2026-11-07 · Measured against `REI-AGENT@5cb9829`,
`bob-intelligence-@be5b233`, `the-dashboard@dc2b54d`.

---

## 0. Correction first: my previous grade was stale

`PROJECT_GRADE.md` graded `REI-AGENT` at **D** on 2026-10-11. That grade was
measured against commit `0f07b12` — a **June** snapshot — because that is what
`origin/master` showed me at the time and I never looked past it.

The real repository, which I only saw once Bob and Karpathys were attached:

| | What I graded | Reality today |
|---|---|---|
| Branches | 2 | **26** |
| Commits on master | ~15 | **149** |
| Master HEAD | `0f07b12` (Jun 8) | `5cb9829` (PR #24) |
| Test files | 10 | **44** |
| CI workflows | 0 | **3** |

There are branches named `phase1/arv-truth`, `phase2c/market-price-bands`,
`fix/signalwire-sha256-webhooks`, `fix/offer-evidence-integrity`,
`feat/three-project-wiring`. Those are the exact problems I was writing audits
about, being worked on in parallel, while I measured a four-month-old tree.

**That is my error, and it is the kind this project keeps producing: I audited
one surface and assumed it was the system.** The findings below are re-measured.

### My findings that are now fixed on current master

| # | Finding | Status |
|---|---|---|
| **9.1** | `_check_dnc` fails open | ✅ **Fixed** — now `raise RuntimeError("DNC verification unavailable")`. Fails closed. This was my #1 item |
| **9.17** | Zero webhook signature verification | ✅ **Fixed** — `api/security.py::valid_signalwire_signature`, HMAC-SHA1, `compare_digest`, handles both raw-body and canonical-param forms |
| **9.18** | No authentication on any route | 🟡 **Partly** — `OperatorAuthentication` middleware wired in `main.py`, gating operator endpoints on `SOURCE_COMMAND_SECRET`. Not all 81 routes |
| **9.6** | `.env.example` empty (0 bytes) | ✅ **Fixed** — 30 lines |
| **9.13** | No CI | ✅ **Fixed** — `backup.yml`, `uptime.yml`, `voice-regression.yml` |
| **9.12** | 10 test files | ✅ **Improved** — 44 |
| Seam | `/api/ingest/bob/brief-created` missing | ✅ **Exists** — `routes/bob.py`, with UUID idempotency key, tenant binding, `schema_version` check, 409 on mismatch, 503 on persistence failure |

I reported that endpoint as missing earlier in this session. **I was wrong** —
I grepped my stale checkout. It exists and is properly bound.

### Still open on current master

| # | Finding | Evidence |
|---|---|---|
| **9.16** | `priority_callback` read by **0** files | Re-measured today. Hot leads and escalations still do not move up the call queue |
| **9.23** | ~138 unbounded queries | 206 `.table()` vs 68 `.limit()` |

My containment survived the merge intact: `execution_context.py` present,
`honor_stop_request` live, and the identity prompt now reads *"an automated home
buying assistant"* — someone tightened my wording, which is an improvement.

The suite could not run here: 23 collection errors, all missing packages
(`pipecat` ×9, `fastapi` ×8, `fakeredis`, `starlette`, `schedule`, `pdfplumber`,
`apscheduler`). **`[UNVERIFIED]`: the pass rate with dependencies installed.**

---

## 1. Bob (`bob-intelligence-`) — **A−**

My `REBUILD_MAP.md` classified this repo `LEGACY — archive it`. **That was
correct for a 21-file snapshot with no tests and is now badly wrong.**

| | Sept audit | Now |
|---|---|---|
| Files | 21 | 88 (45 py) |
| LOC | ~500 | 2,779 |
| Test files | 0 | 11 |
| Test LOC | 0 | **1,231 (44% of the repo)** |
| **Tests passing** | — | **3,455 passed, 17 skipped, 0 failed** |
| Blind `except` | — | **6** (all justified worker-loop handling) |
| Silent `pass` | — | **0** |
| `Decimal` uses | — | 62 · `float` 7 (statistical internals only) |

### Why it earns an A−

**The tests are the best engineering in any of the four repos.**

```python
def test_exact_half_cent_is_correct_in_every_comparable_order():
    ...
    for comps in permutations(payload['comparables']):
        assert compare_sales({...})['point_cents'] == 41569075
```

That computes an **exact oracle with `Fraction`** — rational arithmetic, zero
floating-point error — then asserts the engine matches it across *every
permutation* of inputs. Alongside it, `test_random_exact_reconciliation_order_bounds_and_money_scale`
runs 20 seeds × 250 randomized cases with `deepcopy` to prove no input mutation.

Property-based testing with exact rational oracles, guarding half-cent rounding
and order independence in the money path. REI-AGENT has nothing comparable
anywhere.

**The valuation engine satisfies V2 invariants REI-AGENT violates:**

```
point_cents, supported_low_cents, supported_high_cents
range_meaning: 'observed_adjusted_sale_span_not_statistical_confidence_interval'
quote_authorized: False, offer_authorized: False
rejected_comparables, review_reasons
evidence_verification: 'trusted_input_attestations_not_independent_source_research'
production_ready: False
```

Invariant #10 (no valuation without a range) — satisfied. It also states what
the range **is not**, which is rarer and more honest than stating what it is.
`quote_authorized: False` fails closed by default.

**Durable execution, already built.** `claim_brief_jobs` / `complete_brief_job` /
`fail_brief_job` are Postgres RPCs taking a `p_lease_seconds` and validating a
`p_token` lease on completion. That is my Gate 4, server-side and atomic.

**Tenant scoping on every query**, not just some: `.eq('tenant_id', …)` on each
select and `p_tenant_id` on each RPC. Suppression is enforced in the query
itself — `.eq('opted_out', False).eq('dnc_blocked', False).neq('stage','dead')`
— so a suppressed lead is never even claimed. And every query is `.limit()`ed.

**`config.py` fails closed on misconfiguration:** UUID validation on tenant,
HTTPS-only URLs, rejects URLs carrying credentials or a path/query/fragment,
integer bounds, and a **placeholder detector** that refuses a service key
containing `placeholder`, `your-` or `example`.

### Why not an A

- `engine.py` has a **111-line function**; `local_benchmark.py` a 91-line one.
- `market_research.py` uses `float` in the model layer. Defensible for
  log-space regression, but the cents boundary is where a bug would hide and
  the conversion (`log_to_cents`) is the thinnest-tested part.
- The repo has **no HTTP surface at all** — it is a pure worker. Nothing to
  attack, but also nothing to audit for auth.

---

## 2. Karpathys (`the-dashboard`) — **B+**

| | Sept audit | Now |
|---|---|---|
| Files | ~670 | **1,203** (391 backend py) |
| Backend LOC | — | 47,877 |
| Test files | 28 | **46 + 5 safety** |
| Test LOC | — | **13,862 (29%)** |
| Blind `except` | — | **43 in 47,877 LOC** |
| Silent `pass` | — | 7 |
| Functions > 80 lines | — | **4** (max 99) |

For scale: REI-AGENT has **247** blind handlers in 20,197 LOC. Karpathys has
43 in 47,877 — roughly **17× cleaner per line**. `governance`, `models`,
`repositories`, `transcripts`, `context` and `research` have **zero** between
them.

### The CI is better than what I specified in Gates 3 and 4

```yaml
services: postgres:17, redis:8   (with health checks)
- ruff check .
- pytest tests tests_safety -q --junitxml=test-results.xml
- python scripts/initialize_database.py --roundtrip-test
- python scripts/verify_schema.py
- alembic current
- checkout Lavish213/REI-AGENT @ 5b6a2f5e...   → _rei-contract
- checkout Lavish213/Bob-Intelligence- @ 7d265ab... → _bob-contract
- python scripts/verify_voice_outbox_boundary.py   # restart + receipt recovery
- python scripts/verify_project_connections.py
frontend: typecheck · lint · test · build · npm audit · Playwright
```

- **Schema reproducibility** — `initialize_database.py --roundtrip-test` plus
  `verify_schema.py`. That is my Gate 1A step 5, done.
- **Cross-repo contract pinning** — REI-AGENT and Bob are checked out at exact
  commits and verified against. I have never seen a solo-operator project do this.
- **Outbox restart recovery tested** — "Real HTTP voice outbox restart and
  receipt recovery." That is my Gate 4's kill-the-worker test.
- 8 Alembic migrations, so the schema is in version control here.

### Finding 9.5 is fixed, and fixed better than I specified

I flagged `if _WEBHOOK_SECRET and secret != …` as failing open on an unset env
var. Now:

```python
raise HTTPException(503, "Webhook authentication is not configured")   # closed
if not hmac.compare_digest(...)                                        # timing-safe
router = APIRouter(dependencies=[Depends(verify_karpathys_secret)])    # router-wide
```

The router-level dependency is the part I did not think of: a new endpoint
added to that router cannot forget the check.

`backend/security/` now holds `webhooks.py`, `websocket_tickets.py`,
`request_limits.py`, `rate_limits.py`, `rbac.py`, `permissions.py`,
`legacy_writes.py` — my Gate 1.3, 1.4 and 1.5, present as modules.

### Why not an A

- **I could not run the suite.** It needs Postgres 17 and Redis; neither is
  available here. 13,862 LOC of tests that I have not executed is evidence of
  intent, not of passing. `[UNVERIFIED]`
- `backend/sophia/` is still 16 files. The parallel Sophia session/turn runtime
  persists, so `REBUILD_MAP` §8.2 stands: Sophia's runtime is still split across
  three repositories.
- `services/business_evidence.py::validate_snapshot` is 99 lines; a validator
  that long is hard to argue correct.
- 35 files and 4,346 LOC in `backend/api` carry 15 of the 43 blind handlers —
  the API edge is the least disciplined part of an otherwise disciplined repo.

---

## 3. The real defects are in the seams — again

Both repos are individually strong. What they agree on is where the problems
are, and both new findings are at the Bob → REI boundary.

### 82 — REI-AGENT discards every safety guard Bob computes

Bob's `CallBrief` is `schema_version 2.0` and carries:

```python
confidence: float = 0.0
expires_at: str      = <created + ttl_hours>
blocked_reasons: list[str]
ready_for_call: bool = False      # defaults to NOT ready
```

`REI-AGENT/backend/voice/call_brief_loader.py` reads `phase`, `missing_box`,
`mood`, `avoid`, `escalation_rules`, `opener_hint`. Measured reads of the rest,
across the loader, preloader and agent:

| Field | Read by |
|---|---|
| `ready_for_call` | **0** |
| `expires_at` | **0** |
| `blocked_reasons` | **0** |
| `schema_version` | **0** |

So Bob decides a brief is **not ready for a call**, says **why**, and stamps
**when it goes stale** — and Sophia loads it and proceeds anyway.

This is worse than the old version of this bug. Bob now produces exactly the
guard V2 invariant #11 demands ("Sophia never acts on an expired strategy"), and
the consumer throws it on the floor. The fix is about fifteen lines in
`call_brief_loader.py`.

Bob also sets `phase='WRAP'` and `objective='Do not contact this seller. Honor
suppression.'` when `opted_out` or `dnc_blocked` is true. REI's loader maps
`WRAP → STAGE_5_WRAP` and never surfaces that objective as a hard stop.

### 83 — The `missing_box` enums have diverged

| | Values |
|---|---|
| **Bob** `CHECKBOX_PRIORITY` | `right_person`, `property_confirmed`, `occupancy`, `condition`, `timeline`, `motivation`, `next_step` |
| **REI** `MissingBox` Literal | `condition`, `timeline`, `motivation`, `next_step`, `identity`, `occupancy`, `none` |

Bob emits `right_person` and `property_confirmed`; neither is a legal value in
REI's typed contract. REI expects `identity`, which Bob never emits. Python
`Literal` is not enforced at runtime, so the value flows silently into
`call_ctx.bob_missing_box` and whatever reads it sees something unrecognised.

Two typed contracts, same name, incompatible vocabularies — the duplicate-truth
failure mode in its purest form.

### 84 — Bob's valuation engine prices nothing

`backend/valuation/` is consumed only by Bob's own `brief_generator.py`. Nothing
in REI-AGENT references `supported_low_cents`, `quote_authorized`, or the engine
at all. The best-tested valuation code you own is not pricing a single deal,
while REI's `comps/calculator.py` — zero tests, five quality signals computed
and discarded, a cosmetic ±5% band — is.

---

## 4. Revised grades

| Repo | Grade | One line |
|---|---|---|
| **Bob** (`bob-intelligence-`) | **A−** | Exact-oracle property tests, ranges, leases, tenant scoping, fail-closed config. Not archivable — it is the best code here |
| **Karpathys** (`the-dashboard`) | **B+** | Cross-repo contract CI, schema round-trip, outbox restart recovery, 29% tests. Unexecuted here, and still holds a third Sophia |
| **REI-AGENT** | **C−**, up from D | DNC fails closed, webhooks verified, CI exists, `.env.example` populated, auth middleware landed. Still ~138 unbounded queries and `priority_callback` goes nowhere |

### What this changes in the plan

1. **`REBUILD_MAP.md` §6 is void.** Bob is not `LEGACY`. The valuation merge
   direction reverses: Bob's engine comes **into** REI-AGENT.
2. **Karpathys' CI is the template.** Do not design a new one for REI-AGENT;
   copy `verify.yml`, including the cross-repo contract pins.
3. **Findings 82 and 83 are the cheapest high-value fixes left** — a loader
   that honours `ready_for_call` and `expires_at`, and one reconciled enum.
   Together, well under a day.
4. **Re-grade before planning, always.** I graded a four-month-old tree and
   wrote three documents on top of it. Check `git log origin/<default>` and the
   branch list before measuring anything.

---

*Bob's suite was executed here: 3,455 passed, 0 failed. Karpathys' was not —
it needs Postgres 17 and Redis. REI-AGENT's could not collect for missing
packages. Every other number was measured by AST pass or grep against the
commits named at the top.*
