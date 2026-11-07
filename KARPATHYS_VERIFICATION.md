# Karpathys — Full CI Verification

**Date:** 2026-11-07 · **Subject:** `the-dashboard@dc2b54d`
**Mode:** read-only. Nothing in `the-dashboard` was modified.

This closes the largest `[UNVERIFIED]` item across every audit I have written:
Karpathys' 13,862 lines of tests, which I graded **B+ on intent** because I had
never executed them.

**They are now executed. Every CI gate passes.**

---

## How I stood it up

CI requires Postgres 17 and Redis 8. This container had Postgres **16.15**
server binaries at `/usr/lib/postgresql/16/bin` and Redis **7.0.15** already
present. `initdb` refuses to run as root, so the cluster was initialised as the
existing unprivileged `postgres` user in a directory it owns.

Cross-repo contracts were supplied exactly as CI supplies them:

| CI input | What I provided |
|---|---|
| `REI_REPO` | `git worktree` of `REI-AGENT` at the pinned `5b6a2f5e` |
| `BOB_REPO` | `git worktree` of `bob-intelligence-` at the pinned `7d265ab8` |
| `REI_CONTRACT_PYTHON` | isolated venv with CI's exact pins — `httpx==0.28.1`, `loguru==0.7.3`, `supabase==2.32.0`, `pytest==9.0.2`, `fastapi==0.143.2`, `uvicorn==0.54.0` |

**Version caveat:** Postgres 16 and Redis 7 rather than CI's 17 and 8. Every
gate passed on these versions; a version-specific failure on 17/8 would not
have been caught here. `[UNVERIFIED on the pinned versions]`

---

## Results — all eight gates

| # | CI step | Result |
|---|---|---|
| 1 | `pytest tests tests_safety -q` | **1,261 passed, 0 failed** |
| 2 | `ruff check .` | **All checks passed** |
| 3 | `initialize_database.py --roundtrip-test` | **"Verified 44 migrated tables and 46 enums against all registered models"** |
| 4 | `verify_schema.py` | **Verified, no drift** |
| 5 | `alembic current` | `001_enum_additions (head)` |
| 6 | `verify_voice_outbox_boundary.py` | **passed** — see below |
| 7 | `verify_project_connections.py` | **passed** — see below |
| 8 | `verify-production-compose.py` | **passed** — see below |

### Gate 3 of my roadmap — reproducible schema — is done

```
Verified 44 migrated tables and 46 enums against all registered models
Initialized frozen platform schema and recorded existing migration head
Existing schema and migration head verified without changing application data
```

An empty database was built entirely from committed migrations and then diffed
against the SQLAlchemy models with zero drift. That is precisely what my
`ROADMAP.md` Gate 1A step 5 and Gate 3 asked for, and it works today.

My first attempt reported drift — because I ran `verify_schema.py` **before**
`initialize_database.py`. Running CI's steps in CI's order resolved it. The
drift was my sequencing error, not a defect.

### Gate 4 of my roadmap — durable execution — is proven

```
Voice outbox boundary passed: real HTTP, PostgreSQL, two producer restarts,
pre-write outage and post-commit acknowledgement loss
```

Read that carefully. It is not a mocked outbox test. It uses **real HTTP and
real PostgreSQL**, kills the producer **twice**, and injects both a **pre-write
outage** and a **post-commit acknowledgement loss** — the two hardest cases,
where a message is committed but the sender never learns it.

That is the kill-the-worker test my roadmap specified for Gate 4:

> *"Kill a worker before the provider request, after provider acceptance, and
> during callback processing. No injected failure may increase contact authority
> or lose an acknowledged seller request."*

It exists and it passes.

### Authenticated boundary, both directions

```
Project connections passed: actual PostgreSQL plus authenticated HTTP in both
directions; wrong command secret denied; Bob health is explicitly a fixture
```

Two things worth noting. **A wrong command secret is denied** — the negative
case is tested, not just the happy path. And the script says outright that
**Bob health is a fixture**, rather than implying it probed a live Bob. That is
the same refusal to overclaim I found throughout Bob's own artifacts.

### Production configuration

```
Production Compose merge verified: private services, no development mounts,
explicit production identity, authenticated Redis, build-time browser origins,
proxy domain
```

Development mounts and public service exposure are checked for and absent.

---

## Grade revision: B+ → A−

| Dimension | Evidence |
|---|---|
| Test volume and health | 1,261 passing, **0 failing** |
| Lint | clean |
| Schema reproducibility | 44 tables / 46 enums from migrations, no drift |
| Durable execution | proven under 2 restarts, pre-write outage, post-commit ack loss, real HTTP + Postgres |
| Negative-path testing | wrong secret denied; fixtures labelled as fixtures |
| Cross-repo contracts | REI and Bob pinned at exact commits and verified |
| Production config | private services, no dev mounts, authenticated Redis |

**Why not an A.** Two things, both real:

1. **`backend/sophia/` is still 16 files.** The parallel Sophia session/turn
   runtime persists, so `REBUILD_MAP` §8.2 stands — Sophia's runtime remains
   split across three repositories. Duplicate truth, unresolved.
2. **Verified on Postgres 16 / Redis 7**, not CI's pinned 17 / 8.

---

## Consolidated grades, final

| | Grade | Basis |
|---|---|---|
| **Karpathys** (`the-dashboard`) | **A−** | All 8 CI gates executed and passing here |
| **Bob** (`bob-intelligence-`) | **B−** | 3,455 tests, 79.5% coverage, 457 mutations / 0 violations — but 3 of 10 engines exist and the headline accuracy measures a kernel |
| **REI-AGENT** | **C+** | 1,608 passing, 0 logic failures; `priority_callback` dead and ~138 unbounded queries remain |
| **System overall** | **B−** | Each repo now grades well; the seams between them are the remaining problem |

The overall grade moved from **D** to **B−** across this session. Almost none of
that came from code I wrote. It came from measuring things I had previously
assumed, and from work your other sessions had already landed.

---

## What is genuinely still open

**In REI-AGENT:**
- `priority_callback` written on every HOT disposition and escalation, read by **0 files** — hot leads still do not move up the call queue
- ~138 unbounded queries (206 `.table()` against 68 `.limit()`)
- AI disclosure is prompt-resident, so still model-discretionary
- 14 test files unexercised here (`pipecat`/`docopt` build failure)

**In Bob:**
- 7 of 10 required engines absent; the Rehab Engine is the keystone
- `after_repair` is `as_is` relabeled — identical point, low and high
- Interval coverage structurally capped at `(n−1)/(n+1)`; 50% at the 3-comp minimum
- The published 9.86% MdAPE measures `reconcile_indications`, not `compare_sales`

**Across all three:**
- `backend/sophia/` — Sophia's runtime still exists in three places
- Bob's valuation engine prices nothing in REI-AGENT

**Unverifiable from any repository:** live Supabase RLS, Railway and Vercel
configuration, SignalWire account state, consent records, and whether any
licensed property-data feed is actually available. Those need evidence
collection, and treating them as blockers rather than assumed-good remains
correct.

---

## Scorecard for this session's measurement work

| Executed | Result |
|---|---|
| Bob's suite | 3,455 passed / 0 failed · 79.5% coverage |
| Bob adversarial + mutation | 457 mutations / **0 authorization violations** |
| Bob property tests | 9 of 10 at 3,000 examples each |
| Bob simulations | ~2.04M |
| REI-AGENT's suite | 1,608 passed / **0 logic failures** |
| **Karpathys' suite + all CI gates** | **1,261 passed / 0 failed · 8 of 8 gates** |

Nine corrections to my own prior conclusions, five of them from measuring a
stale checkout. The procedural fix is recorded in
`MEASUREMENT_PASS_20261107.md`: resolve and fetch the live default branch
before measuring anything.

*Every number above was produced by a command executed in this session against
the commits named at the top. Nothing in `the-dashboard` or `bob-intelligence-`
was modified.*
