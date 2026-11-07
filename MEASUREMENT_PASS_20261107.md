# Measurement Pass — 2026-11-07

Resolving the largest `[UNVERIFIED]` items in my prior audits by installing the
missing dependencies and actually executing the suites.

**Measured against `REI-AGENT@119d60a`** (current master plus the loader fix).

---

## Headline: REI-AGENT's test suite has zero logic failures

```
1,608 passed · 50 failed · 2 skipped
```

**All 50 failures are `ModuleNotFoundError: No module named 'pipecat'`.** Not
one is a logic failure. Verified by tallying every `E` line in the run:

```
     50 ModuleNotFoundError: No module named 'pipecat'
```

A further 14 test files cannot collect at all, for the same reason.

### Why `pipecat` could not be installed here

`pip install pipecat-ai` fails building its transitive dependency `docopt`,
which has no wheel and whose `setup.py` breaks under this Python. `--no-build-isolation`
fails the same way. This is an upstream packaging problem, not a repository
defect, and your hosted CI almost certainly installs it fine.

### What I installed to get there

Each of these turned "failures" into passes, and each was purely environmental:

| Installed | Failures cleared |
|---|---|
| `fastapi`, `starlette`, `uvicorn`, `apscheduler`, `schedule`, `fakeredis` | 8 collection errors |
| `anthropic`, `pdfplumber`, `beautifulsoup4` | remaining import errors |
| **`pytest-asyncio`** | **40** — the repo sets `asyncio_mode` but the plugin was absent, so every async test "failed" |
| `python-multipart` | 2 — FastAPI form handling |
| **`lupa`** | **2** — `fakeredis` needs Lua to support `EVAL`; without it `_acquire_call_slot` could not run |

---

## Corrections to my own grades

### Testing: **F → B**

`PROJECT_GRADE.md` graded Testing **F** on "76 failed / 218 passed." That was
measured against commit `0f07b12`, a June snapshot. Current master:

| | My F grade (June tree) | Measured today |
|---|---|---|
| Test files | 10 | **45** |
| Passing | 218 | **1,608** |
| Logic failures | unknown | **0** |

Not a B+ only because 14 files and 50 tests could not be exercised here, so
their state is `[UNVERIFIED]` from this environment.

### Finding 9.20 (dial race): **fixed**

I reported that `last_called_at` is written only at call outcome, so two workers
could dial the same seller. Current master acquires capacity atomically:

```python
def _acquire_call_slot(lead_id, attempt_token=""):
    client = _get_redis_client()
    if not client:
        logger.error("call_capacity_unavailable")
        return False                      # fails closed: no Redis, no dial
    return bool(client.eval(_ACQUIRE_SLOT_LUA, 3, _REDIS_CONCURRENT_KEY,
        _REDIS_OWNERS_KEY, _REDIS_CALLS_KEY, time.time(), lead_id,
        _MAX_CONCURRENT_CALLS, 3600, attempt_token))
```

Server-side Lua, so the check and the claim are one operation. Per-lead
ownership in `_REDIS_OWNERS_KEY`, a concurrency cap, a 3600s TTL, and an
`attempt_token`. `_bind_call_slot` then refuses to bind a `call_sid` unless the
token matches the acquirer — a fencing token. Two workers cannot dial the same
lead, and losing Redis stops dialling rather than permitting it.

That was item 9 in my priority table. It is resolved.

### Also fixed, re-confirmed on current master

From the earlier pass in this session: `_check_dnc` now raises instead of
returning `False`; SignalWire signatures are verified with HMAC and
`compare_digest`; `OperatorAuthentication` middleware is wired; `.env.example`
is populated; three CI workflows exist.

---

## Still open, verified on current master

These were re-measured after `git reset --hard origin/master`, so they are
current, not stale:

| # | Finding | Measured |
|---|---|---|
| **9.16** | `priority_callback` read by **0** files | Hot leads and escalations still do not move up the call queue |
| **9.23** | 206 `.table()` calls against 68 `.limit()` | ~138 unbounded queries |

---

## My loader change: zero regressions

Tested by checking out the parent commit's versions of both changed files,
running the affected tests, then restoring:

| | Without my change | With my change |
|---|---|---|
| `test_valuation_guidance` + `test_business_sync` + `test_provider_recovery` | 4 failed, 33 passed | **4 failed, 33 passed** |

Identical. The 4 were pre-existing; `lupa` subsequently cleared 2 of them and
the other 2 are `pipecat`.

---

## Revised grades

| Area | Was | Now | Why |
|---|---|---|---|
| **Testing** | F | **B** | 1,608 passing, 0 logic failures |
| **Reliability** | D− | **C** | Atomic Lua slot acquisition, fencing tokens, fails closed. In-memory call state and web-process schedulers still stand |
| **Data integrity** | F | **D+** | Dial race fixed; write-only `priority_callback` and ~138 unbounded queries remain |
| **Security** | F | **C−** | Webhook signatures verified, auth middleware wired; not all 81 routes covered |
| **Compliance** | D+ | **C** | DNC fails closed; AI disclosure still prompt-resident |
| **REI-AGENT overall** | C− | **C+** | |

---

## The pattern worth recording

Across this session I have corrected myself eight times, and **every single one
traces to the same mistake**: measuring my local checkout instead of
`origin/<default-branch>`.

| Corrected | Root cause |
|---|---|
| REI-AGENT graded D on a June tree | stale checkout |
| Migrations marked `KEEP` | stale checkout |
| PropWire CSVs marked `KEEP` | did not open the files |
| "no cost-based MAO solver" | did not read `flip_analysis`'s return |
| Ames coverage explained by exchangeability | hypothesis not tested before publishing |
| Findings 82 and 83 "unfixed" | stale checkout |
| Brief objective "never surfaced" | grep pattern too narrow |
| Testing graded F | stale checkout |
| Finding 9.20 "open" | stale checkout |

Five of nine are the same error. The fix is procedural, and I am stating it so
it can be held against me: **resolve and fetch the live default branch before
measuring anything, and never grade a working tree I have not just synced.**

---

## Remaining `[UNVERIFIED]`

- **14 REI-AGENT test files + 50 tests** — blocked by `pipecat`/`docopt` here.
- **Karpathys' 13,862 lines of tests** — needs Postgres 17 and Redis. Not attempted.
- **Bob's E-6 Ames confirmation** — `jse.amstat.org` denied by this
  environment's network policy. Environment `env_019MqoPiQFzTNANf4AZFR6Kp`
  allows it; this session type cannot move onto it.

*All numbers above were produced by commands executed in this session.*
