# Bob Intelligence — Read-Only Audit

**Cycle:** 1 · **Date:** 2026-11-07 · **Mode:** READ-ONLY. No code modified, no
deploys, no database writes, no external communications.

**Subject:** `bob-intelligence-@be5b233` (default branch, current)
**Context:** `REI-AGENT@5cb9829`, `the-dashboard@dc2b54d`

Everything below was measured in this session by file read, AST pass, or test
execution. Where a metric cannot be measured it says **NOT MEASURED**, and the
reason. No result is inferred or invented.

---

## PHASE 1 — EXISTING SYSTEM AUDIT

### Inventory

| | Count |
|---|---|
| Tracked files | 88 |
| Python files | 36 (2,779 LOC) |
| Test files | 11 (1,231 LOC — **44% of the repo**) |
| Research documents | 16 in `docs/`, including 6 JSON evidence artifacts |
| Migrations | 3 |
| CI workflows | 1 (`bob-regression.yml`) |

### Execution evidence (run in this session)

```
pytest -q  →  3,455 passed, 17 skipped, 0 failed   (5.26s)
```

That is a real run, not a claim. It required installing `python-dotenv`; the
other three dependencies were already present.

### Module map

| Path | LOC | What it actually is |
|---|---|---|
| `valuation/engine.py` | 197 | `compare_sales` — evidence-adjusted sales comparison; `reconcile_indications`; `validate_features`; `valuation_for_brief` |
| `valuation/market_research.py` | 195 | Model research: log-space regression, calibration radii |
| `valuation/local_benchmark.py` | 127 | Offline benchmark harness with dataset checksums |
| `valuation/finance.py` | 77 | `screening_mao`, `flip_analysis`, `rental_analysis`, `mortgage_payment`, `cost_approach`, `cash_on_cash_return`, `repairs_with_contingency` |
| `valuation/candidates.py` | 50 | `rank_candidates` — comparable selection |
| `valuation/san_joaquin.py` | 72 | County HPI series handling, FIPS-pinned |
| `valuation/california.py` | 37 | CA-specific acceptance rules |
| `call_planner/*` | 188 | 5 modules producing Sophia's brief |
| `contracts/call_brief.py` | 30 | `CallBrief`, schema 2.0, 7-rung `CHECKBOX_PRIORITY` |
| `worker/loop.py` | 70 | Job loop with lease claim / complete / fail |
| `events/bob_events.py` | 37 | Outbound event delivery with lease tokens |
| `db/client.py` | 70 | Supabase access; 5 Postgres RPCs |
| `config.py` | 55 | Settings with validation |
| **`intel/`** | **0** | **Empty `__init__.py`** |
| **`scoring/`** | **0** | **Empty `__init__.py`** |
| `decisions/decision_logger.py` | 6 | Stub |

### Contracts and integrations

**Outbound (Bob → REI-AGENT):** `POST {REI_COMMAND_URL}/api/ingest/bob/brief-created`,
authenticated with `KARPATHYS_WEBHOOK_SECRET`. Verified present on the REI side
at `backend/api/routes/bob.py`, which validates a UUID idempotency key, tenant
binding, event type, and `schema_version == '2.0'`, returning 409 on mismatch
and 503 on persistence failure.

**Shared database:** Bob reads `leads` and `intel_packets` and writes briefs
through RPCs `bob_claim_brief_jobs`, `bob_complete_brief_job`,
`bob_fail_brief_job`, `bob_claim_events`, `finish_event`. All five take
`p_tenant_id`; the completion RPCs validate a `p_token` lease.

**Consumed by:** `valuation/` is referenced only by
`call_planner/brief_generator.py`. Nothing in REI-AGENT references the
valuation engine.

### Engineering quality, measured

| | Bob | REI-AGENT (for scale) |
|---|---|---|
| LOC | 2,779 | 20,197 |
| Broad/bare `except` | **6** | 247 |
| Silent `pass` handlers | **0** | 34 |
| `Decimal` uses / `float` uses | 62 / 7 | — / float money math present |
| Functions > 80 lines | 2 (111, 91) | 1 at 158 |

The 6 broad handlers are all in `worker/loop.py` and `events/bob_events.py`.
Each increments an error counter and logs `type(error).__name__` rather than the
message, which avoids writing payload data into logs. For a job loop that must
not die on one bad record, this is correct.

`config.py` fails closed on misconfiguration: UUID validation on tenant,
HTTPS-only URLs, rejection of URLs carrying credentials or a path/query/
fragment, integer bounds, and a placeholder detector that refuses a service key
containing `placeholder`, `your-` or `example`.

### Test methodology — the strongest asset in the system

`tests/test_valuation_stress.py` builds an **exact oracle using `Fraction`**
(rational arithmetic, zero floating-point error) and asserts the engine matches
it across *every permutation* of comparables:

```python
for comps in permutations(payload['comparables']):
    assert compare_sales({**payload, 'comparables': list(comps)})['point_cents'] == 41569075
```

Alongside it, 20 seeds × 250 randomized cases verify order-independence,
money-scale correctness and non-mutation of inputs via `deepcopy`.

This is property-based testing with an exact reference oracle, applied to the
money path. No other repository in this system has anything comparable.

---

## PHASE 8 (partial) — BASELINE EVALUATION

The directive asks for actual measured results. They exist, in
`docs/VALUATION-BENCHMARK-20261014.json`, and the methodology holds up.

### Dataset and controls

| | |
|---|---|
| Source | Ames, Iowa housing (`jse.amstat.org`), SHA-256 pinned |
| Rows | 2,930 → 1,943 retained after two documented exclusions |
| Target leakage | Subject sale price hidden from ranking **and** estimation, revealed only for scoring |
| Lookahead | No subject, same-month, or later sale used as a comp |
| Held-out design | 2009 = development diagnostic; **ranking frozen before 2010 evaluation** |
| Protected attributes | "no demographic variables" |

That is a clean held-out protocol with leakage controls stated explicitly.

### Measured ARV-proxy accuracy — held-out year 2010

| Metric | Bob (`feature_ranked`) | Random same-neighborhood baseline |
|---|---|---|
| Subjects | 215 | 4,300 draws |
| **MdAPE** | **9.86%** | 13.68% |
| MAPE | 13.25% | 19.34% |
| MAE | $22,881 | $33,603 |
| Signed bias | **+0.37%** | +3.10% |
| Within 10% | 110 / 215 (51.2%) | 1,691 / 4,300 (39.3%) |
| Worst APE | 131.6% | 209.1% |
| F grades (>20% error) | 48 / 215 (22.3%) | 1,522 / 4,300 (35.4%) |

Development year 2009: Bob 8.58% MdAPE vs baseline 14.37%.

Per-seed random MdAPE spanned 11.78%–15.30% across 20 seeds. **Bob's 9.86% beats
every individual seed**, so the improvement is not seed luck.

### Against Part 22's stated targets

| Objective | Target | Measured | Verdict |
|---|---|---|---|
| **1 — False HOT BUY rate** | −50% baseline, <5% long-term | **NOT MEASURED** | Undefined: Bob has no HOT BUY classifier. The metric cannot exist until Part 18 does |
| **2 — ARV MdAPE** | <10% initial, <7% stretch | **9.86%** held-out | Initial target **met on a proxy**; stretch not met |
| 2 — Valuation bias | — | **+0.37%** | Near-unbiased |
| 2 — Interval coverage | — | **61.9%** (133/215) | **Measured, and worse than baseline's 68.1%** |
| 2 — Neighborhood / property-type error | — | **NOT MEASURED** | Not stratified in the artifact |
| **3 — Hidden-gem yield** | Increase | **NOT MEASURED** | No hidden-gem scoring exists |

### Two findings the numbers force

**B-1 — The measured accuracy is not ARV accuracy.** The benchmark scores
**as-is sale price** in Ames, Iowa, 2009–2010. The artifact says so itself:
*"Single old Iowa market does not establish current California or after-repair
accuracy."* Part 5 requires After Repair Value for San Joaquin County. The
9.86% figure is a credible *method* signal and is **not** evidence of ARV
accuracy in the operating market. Severity: high — it is the number most likely
to be quoted as if it were.

**B-2 — The supported range under-covers.** *(Superseded 2026-11-07 by
finding B-6: the cause is combinatorial, not calibration. Coverage is capped at
`(n-1)/(n+1)` by comparable count — 50% at Bob's 3-comp minimum. See
`BOB_EXPERIMENT_LOG.md` E-5.)*
Interval coverage on held-out 2010: Bob 133/215 = **61.9%**; random baseline
2,930/4,300 = **68.1%**. Bob's point estimate improved while its interval got
*narrower than warranted*. The engine labels the field honestly
(`range_meaning: 'observed_adjusted_sale_span_not_statistical_confidence_interval'`),
so this is not a false claim — but Part 5 requires "a supported valuation range
and confidence assessment," and a 62%-coverage band presented next to a 9.86%
MdAPE invites over-confidence. Severity: high.

Worst-case examples from the artifact make the tail concrete: a property that
sold for **$62,383** was estimated at **$127,178** (+104%); another sold at
$63,000 against a $120,352 estimate. 22.3% of held-out subjects graded F.
Those are exactly the cases that would become false HOT BUYs once a HOT BUY
classifier exists.

---

## PHASE 2 — INTELLIGENCE GAP ANALYSIS

Measured against Part 17's ten required components.

| # | Required component | Status | Evidence |
|---|---|---|---|
| 1 | **Market Data Engine** | 🟡 Partial | `market_research.py` is *model* research. No discovery-source collection, no provenance store, no evidence-class fields |
| 2 | **Pattern Engine** | 🔴 **Absent** | `backend/intel/__init__.py` is 0 bytes |
| 3 | **ARV Engine** | 🟡 **Present; kernel measured, production path not** | `engine.py::compare_sales`. **Corrected 2026-11-07:** experiment E-1 proved the benchmark measures `reconcile_indications`, not `compare_sales`, which produced zero advisory prices across all 649 held-out subjects. See `BOB_EXPERIMENT_LOG.md` finding B-5 |
| 4 | **Rehab Engine** | 🔴 **Absent** | `repairs_with_contingency` *accepts* a line-item total. Nothing estimates scope. No $/sqft bands, no 17 categories, no low/expected/high |
| 5 | **Opportunity Engine** | 🔴 **Absent** | `backend/scoring/__init__.py` is 0 bytes. No Opportunity Score, no Hidden Gem Score |
| 6 | **Lockout Engine** | 🔴 **Absent** | No hard-reject, hold, or reopening-condition code anywhere |
| 7 | **Strategy Matrix** | 🔴 **Absent** | `finance.py` has flip and rental *primitives*; no comparison across the 11 strategies |
| 8 | **Simulation Engine** | 🔴 **Absent** | No scenario or Monte Carlo code |
| 9 | **Negotiation Engine** | 🔴 **Absent** | No opening-offer, walk-away, or objection preparation |
| 10 | **Bob Coordinator** | 🟡 Partial | `worker/loop.py` is a job loop, not a decision arbitrator. `brief_generator.py` does narrow coordination |

### Other specified capabilities

| Part | Capability | Status |
|---|---|---|
| 2–3 | Autonomous property discovery | 🔴 **Absent.** Bob reads `leads` that something else discovered |
| 3 | Hidden Gem Score 0–100 | 🔴 Absent |
| 4 | Evidence classification (VERIFIED/REPORTED/ESTIMATED/ASSUMED/UNKNOWN) | 🟡 Partial. `evidence_verification` and `review_reasons` exist on valuation output; no per-fact classification |
| 7 | 70% rule MAO | 🟢 `screening_mao(arv, repairs, multiplier_bps=7000)` — in basis points, integer cents |
| 7 | Cost-based MAO | 🟡 `flip_analysis` takes `target_profit_cents` but there is no cost-based MAO solver |
| 8 | Deal grading A–F by acquisition ratio | 🔴 **Absent.** The A–F in the benchmark grades *valuation error*, not deals — easy to confuse |
| 9 | Seller Motivation Score 0–100 | 🔴 Absent. `brief_generator` reads `seller_mood` with source and freshness gating, but produces no score |
| 11 | Lockout classifications | 🔴 Absent |
| 13 | Scenario + Monte Carlo | 🔴 Absent |
| 16 | Property/Deal/Market/Strategy memory | 🟡 Partial. 3 migrations cover briefs, feedback-health and valuation inputs; no four-way memory with version history |
| 18 | HOT BUY / WATCH / ARCHIVED / NEEDS VERIFICATION | 🔴 **Absent** |
| 26 | Required property output format | 🔴 Absent |
| 30 | Human approval before consequential action | 🟢 `quote_authorized: False`, `offer_authorized: False` default on every valuation |

### Gap severity, ordered by dependency

**Tier 1 — blocks every downstream metric**

1. **Rehab Engine** (#4). Without it `screening_mao` has no `repairs_cents` to
   consume, so MAO, deal grading, opportunity scoring and HOT BUY are all
   unreachable. This is the single highest-leverage gap.
2. **Deal grading by acquisition ratio** (Part 8) and **deal categorization**
   (Part 18). Until these exist, Part 22 Objective 1 is not merely unmeasured —
   it is undefined.

**Tier 2 — required for the stated safety posture**

3. **Lockout Engine** (#6). Part 11 requires deterministic hard stops the model
   cannot override. Nothing implements this.
4. **Interval calibration** (finding B-2). A 62%-coverage range beside a 9.86%
   MdAPE is the most likely source of a confidently wrong recommendation.
5. **California/San-Joaquin ARV validation** (finding B-1). `san_joaquin.py`
   and `california.py` exist and `docs/SAN-JOAQUIN-*` artifacts exist, but the
   accuracy number comes from Iowa as-is sales.

**Tier 3 — capability breadth**

6. Opportunity + Hidden Gem scoring (#5, Part 3)
7. Simulation Engine (#8)
8. Strategy Matrix (#7)
9. Pattern Engine (#2)
10. Negotiation Engine (#9)
11. Discovery (Parts 2–3)

### One cross-system defect carried forward

Previously logged as finding 82, re-confirmed today and relevant here because it
sits on Bob's own output contract: Bob's `CallBrief` carries `ready_for_call`
(default **False**), `expires_at`, `blocked_reasons` and `schema_version`.
`REI-AGENT/backend/voice/call_brief_loader.py` reads **none of them** — measured
0 reads across the loader, preloader and agent. Bob decides a brief is not ready
and says why; Sophia proceeds anyway.

Bob also emits `right_person` and `property_confirmed` as `missing_box` values,
neither of which is a legal member of REI's `MissingBox` Literal, while REI
expects `identity`, which Bob never emits.

Bob is doing its side of this contract correctly. The loss is on the consumer.

---

## BOB INTELLIGENCE — PERFORMANCE REPORT

- **Cycle Number:** 1
- **Baseline Version:** `bob-intelligence-@be5b233`
- **Experiments Completed:** 0 new. One pre-existing benchmark reviewed and its methodology verified
- **Simulations Executed:** 0 new. Pre-existing artifact covers 2 years × (434 + 215) held-out subjects and 20 random seeds
- **Properties Screened:** 0 live. 1,943 historical Ames records in the artifact
- **Verified Hidden Gems:** **NOT MEASURED** — no hidden-gem scoring exists
- **ARV Median Error:** **9.86% MdAPE** on held-out 2010 **as-is Iowa sale prices**. ARV in the operating market: **NOT MEASURED**
- **False HOT BUY Rate:** **NOT MEASURED** — no HOT BUY classifier exists; metric undefined
- **Financial Test Pass Rate:** 3,455 passed / 17 skipped / 0 failed, executed in this session
- **Critical Risk Failures:** 0 in the suite. Two audit findings at high severity (B-1, B-2)
- **Strategy Selection Accuracy:** **NOT MEASURED** — no Strategy Matrix exists
- **Improvements Demonstrated:** None this cycle. This was an audit, not an experiment
- **Regressions Discovered:** None in Bob. Interval coverage is **worse than the random baseline** (61.9% vs 68.1%) — a pre-existing property, not a regression introduced since
- **Composite Quality Score:** **NOT MEASURED.** Part 23 requires 8 weighted metrics; 5 are unmeasurable because their engines do not exist. A composite computed from 3 of 8 would be misleading
- **Remaining Blockers:** Rehab Engine absent → MAO, grading and HOT BUY unreachable → Objectives 1 and 3 undefined
- **Next Experiment:** See below

---

## Next experiment — the one I would run first

**Hypothesis:** Bob's supported range can reach ≥80% interval coverage on the
existing held-out 2010 set without degrading MdAPE beyond 10%, by widening the
band as a function of comparable dispersion rather than reporting the raw
observed adjusted-sale span.

**Why this one:** it needs no new data source, no new engine, and no live
property. The dataset is checksummed and already in the repo, the harness
(`local_benchmark.py`, `scripts/benchmark_valuation.py`) already exists, and the
held-out split is already frozen. It directly addresses the highest-severity
finding, and it is measurable against a baseline that is already recorded.

**Baseline:** MdAPE 9.86%, coverage 61.9%, bias +0.37% (held-out 2010).

**Decision criterion:** promote only if coverage ≥80% **and** MdAPE ≤10.5%
**and** bias stays within ±1%. Report the trade-off curve either way.

**Leakage control:** 2010 is already the frozen evaluation year. Any tuning
must happen on 2009 only, and the 2010 set must be scored once.

---

## What I did not do, and why

Phases 3 through 7, 9 and 10 are not in this document. Each requires either
design authority I was not given (Phase 3 architecture, Phase 10
implementation roadmap) or work that would be speculative until the Tier 1 gaps
are decided (Phase 4's grading framework depends on the Rehab Engine's output
shape; Phase 5's discovery research depends on which data sources are actually
licensed).

Writing them now would produce exactly what Part 31 warns against: an
architecture proposal that sounds intelligent and has not been tested.

**I did not modify any code, run any deployment, write to any database, or send
any external communication.** The only file created is this document.

### Three things I could not verify

- **`[UNVERIFIED]`** Bob's Railway worker runtime behaviour. I read the code and
  ran the suite; I did not observe a production job cycle.
- **`[UNVERIFIED]`** Whether the five `bob_*` Postgres RPCs exist in the live
  database with the signatures `db/client.py` calls. The three migrations in
  Bob's repo define them; I could not query production.
- **`[UNVERIFIED]`** Whether any licensed MLS or property-data feed is actually
  available to this business. Parts 2–3 assume authorized sources; the repo
  contains source-coverage research (`docs/SOURCE-COVERAGE-20261022.md`,
  `docs/PUBLIC-SOURCE-CHECK-20261022.json`) that I reviewed the existence of but
  did not independently validate against provider terms.

---

*Audit performed read-only against `bob-intelligence-@be5b233`. Test run and all
metrics above were executed or read in this session. No implementation is
authorized or proposed.*
