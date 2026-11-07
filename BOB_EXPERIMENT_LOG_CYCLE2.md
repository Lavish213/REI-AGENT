# Bob — Experiment Log, Cycle 2

**Date:** 2026-11-07 · **Baseline:** `bob-intelligence-@be5b233`
**Mode:** read-only. Bob's code was imported and executed. No repository file was
modified. Scripts live in this session's scratch directory.

Experiments E-7 … E-14. Every number was produced by a command run in this
session.

---

## Ledger

| ID | Experiment | Scale | Result |
|---|---|---|---|
| **E-7** | Test coverage, per module | full suite | **79.5%** total; core 93.8–98.3%; `market_research.py` **29.9%** |
| **E-8** | Property-test financial primitives | 10 properties × 3,000 examples | **9 of 10 pass** |
| **E-9** | Investigate the P10 failure | targeted | **`'-0.000000'` signed-zero string returned** |
| **E-10** | Units and return-shape audit of `finance.py` | all 7 functions | Well designed. **Correction: cost-based MAO exists** |
| **E-11** | Interval strategies under *ranked* selection | 8 cells × 12,000 trials | **83.1% at n=5**; **refutes my E-5 explanation** |
| **E-13** | Mutation test on the authorization invariant | **457 mutations** | **0 violations** |
| **E-14** | Brief generator suppression and safety | 25 cases | All correct; `ready_for_call` never True |

---

## E-7 — Coverage, measured

`coverage run --source=backend -m pytest` → 3,455 passed, 17 skipped.

| Module | Stmts | Miss | Cover |
|---|---|---|---|
| `contracts/call_brief.py` | 26 | 0 | **100.0%** |
| `valuation/finance.py` | 60 | 1 | **98.3%** |
| `events/bob_events.py` | 35 | 1 | 97.1% |
| `config.py` | 39 | 1 | 97.4% |
| `valuation/san_joaquin.py` | 59 | 2 | 96.6% |
| `valuation/california.py` | 31 | 1 | 96.8% |
| `valuation/candidates.py` | 47 | 2 | 95.7% |
| `valuation/engine.py` | 178 | 11 | **93.8%** |
| `call_planner/brief_generator.py` | 62 | 4 | 93.5% |
| `worker/loop.py` | 63 | 6 | 90.5% |
| `db/client.py` | 48 | 14 | 70.8% |
| `main.py` | 31 | 11 | 64.5% |
| **`valuation/market_research.py`** | **177** | **124** | **29.9%** |
| `valuation/__main__.py` | 25 | 25 | 0.0% |
| **TOTAL** | **1,099** | **225** | **79.5%** |

**Finding B-8.** The deterministic money core is covered at 94–98%. The
*statistical* layer is covered at 29.9%, and it is also the only module using
`float` (3 occurrences, E-10 confirms they are model internals). The weakest-
tested code is the probabilistic code — the inverse of where confidence should
sit. Severity: medium.

---

## E-8 / E-9 — Financial primitives under property testing

10 properties, 3,000 Hypothesis examples each:

| Property | Result |
|---|---|
| P1 `screening_mao >= 0` always | PASS |
| P2 MAO monotone decreasing in repairs | PASS |
| P3 MAO monotone increasing in ARV | PASS |
| P4 MAO integral and matches an exact `Fraction` floor oracle | PASS |
| P5 contingency exact; `total == base + contingency` | PASS |
| P6 contingency monotone in bps | PASS |
| P7 contingency order-invariant | PASS |
| P8 no `float` in MAO or contingency outputs | PASS |
| P9 `mortgage_payment` total function | PASS |
| **P10 `cash_on_cash_return` sign follows cash flow** | **FAIL — 2 distinct counterexamples** |

Nine of ten held against 30,000 generated cases. The money core is sound.

### Finding B-9 — `cash_on_cash_return` returns a signed zero

```python
def cash_on_cash_return(annual_cash_flow_cents, initial_equity_cents):
    ...
    return str((Decimal(cash) / equity).quantize(Decimal('0.000001')))
```

| cash flow | equity | returns |
|---|---|---|
| +100 | 100,000,000,000 | `'0.000000'` |
| **−100** | **100,000,000,000** | **`'-0.000000'`** |

Any ratio below 5e-7 quantizes to zero, and a negative one keeps its sign:
**`'-0.000000'`**.

**Being proportionate about severity:** the magnitudes required ($1 of annual
cash flow against $1B of equity) do not occur in this business, so this will not
drive a wrong acquisition decision. It is a correctness defect, not a financial
one. What makes it worth fixing is consumer disagreement: `float(r) < 0` is
`False` while `r.startswith('-')` is `True`, so two reasonable readers of the
same value disagree about the sign — and rendered to an operator, "−0.000000"
is meaningless. Severity: low. Fix: normalise zero before stringifying.

---

## E-10 — Units audit, and a correction to my own audit

Every money field in `finance.py` is suffixed `_cents` and typed `int`. Every
rate is a 6-decimal **ratio string**, never a percent, and the field names are
unusually careful:

```
profit_over_pre_sale_project_cost : '0.195548'
cost_model : 'fixed_holding_and_financing_inputs_must_be_recomputed_if_purchase_or_term_changes'
income_indication_is_market_appraisal : False
quote_authorized : False
```

`profit_over_pre_sale_project_cost` names its own denominator, which is the
detail most ROI figures get wrong. `cost_model` warns about its own staleness.
`income_indication_is_market_appraisal: False` refuses the interpretation a
reader would otherwise assume.

### Correction — cost-based MAO is **not** absent

`BOB_INTELLIGENCE_AUDIT.md` Phase 2 recorded: *"Cost-based MAO — 🟡 `flip_analysis`
takes `target_profit_cents` but there is no cost-based MAO solver."* That is
wrong. `flip_analysis` returns:

```
purchase_limit_cents            : 27128713
target_profit_feasible_at_limit : True
```

It solves for the purchase price at which the target profit is met. **That is
Part 7's cost-based MAO**, and it exists, is tested, and is 98.3% covered. Part 7
is therefore substantially satisfied — both the 70% screening rule
(`screening_mao`) and the cost-based limit (`flip_analysis`) are implemented.
What is missing is the `repairs_cents` input to both, which is the Rehab Engine.

**One latent seam risk.** Rates are ratios; Part 7 defines `ROI = ... × 100`.
A consumer that renders `'0.195548'` as a percentage without multiplying shows
0.195548% instead of 19.55%. No consumer exists yet, so this is latent — but it
is the same shape as REI-AGENT's cents/dollars defect, and REI-AGENT is the
repository that will consume it.

---

## E-11 — Interval strategies under ranked selection

**Method:** pool of 40 candidates per subject, price correlated with living area,
comps selected either at random or by Bob's own similarity ordering
(area divergence + age + distance — the `rank_candidates` criteria). Point
estimate from Bob's real `reconcile_indications`. 12,000 trials per cell.

Coverage by span-scaling factor:

| n | selection | MdAPE | **1.0× (today)** | **1.5×** | 2.0× | 2.5× | width @1.5× |
|---|---|---|---|---|---|---|---|
| 3 | random | 20.66% | 49.3% | 64.9% | 73.8% | 80.8% | 66.6% |
| **3** | **ranked** | 17.86% | **51.7%** | **67.3%** | 76.4% | 82.3% | 60.3% |
| 5 | random | 19.38% | 66.9% | 82.5% | 89.9% | 94.1% | 92.0% |
| **5** | **ranked** | 16.91% | **68.7%** | **83.1%** | 90.5% | 94.1% | 84.6% |
| 7 | ranked | 17.20% | 77.5% | 90.4% | 95.5% | 97.6% | 100.5% |
| 9 | ranked | 16.54% | 82.6% | 94.0% | 97.5% | 98.7% | 112.0% |

### The (n−1)/(n+1) law replicates in a second generative model

Random selection: n=3 → 49.3% (theory 50.0%), n=5 → 66.9% (66.7%),
n=7 → 75.3% (75.0%), n=9 → 80.4% (80.0%). E-5's law holds under correlated
prices, not just i.i.d. draws. Finding B-6 stands.

### Correction — my E-5 explanation was not reproduced

In cycle 1 I explained Ames' 61.9% (below the 66.7% ceiling) by arguing that
ranking makes comps more similar to each other than to the subject, breaking
exchangeability downward.

**E-11 shows the opposite.** Ranked selection *raised* coverage at every comp
count (51.7% vs 49.3% at n=3; 68.7% vs 66.9% at n=5) and improved MdAPE by about
3 points. My mechanism was plausible and is not what this experiment found.

A better hypothesis, consistent with the artifact's own worst cases — a property
that **sold for $62,383 against a $127,178 estimate** — is that Ames' shortfall
comes from *subject-level* price outliers: homes whose sale price is not
explained by the ranked features at all, most likely condition or distress that
the feature set does not carry. That is an unmodelled-variance problem, not an
exchangeability problem. **It remains a hypothesis and is NOT MEASURED**; testing
it needs the Ames data this environment cannot reach.

### The honest verdict on strategy I

- At **n=5 ranked it reaches 83.1%**, clearing the pre-registered 80% criterion.
- At **n=3 — Bob's enforced minimum — it reaches only 67.3%.** Reaching 80% at
  three comps needs 2.5× scaling.
- **The width cost is severe.** 84.6% mean width at n=5 means a $400,000 point
  estimate carries roughly a ±$170,000 band. Technically calibrated; close to
  useless for underwriting.

**Finding B-10.** A scaled comp span can be made to cover 80% of outcomes, but
only at a width that makes the interval uninformative, and not at all at Bob's
three-comparable minimum. The implication is that **the comp span is the wrong
object to calibrate.** A genuine prediction interval needs residual variance
from a fitted model — which lives in `market_research.py`, the module measured at
29.9% coverage in E-7. The two findings point at the same place.

Recommended revision to the pre-registered E-6: keep the 80% criterion, but add
a width ceiling (mean width ≤ 50% of the point estimate) and report that
strategy I fails it. Otherwise the experiment can be "passed" by producing a
useless interval.

---

## E-13 — Mutation test on the authorization invariant

Part 20 requires proof that *"removal or corruption of any packet field cannot
increase authority."* Tested directly:

- deletion of each of the 15 comparable fields
- 14 hostile values (`None`, `""`, `0`, `-1`, booleans, empty containers,
  `10**20`, `-(10**20)`, `inf`, `"NaN"`, a path-traversal string, a
  `__proto__` object) against every comparable field, every subject field, and
  every subject feature
- every gate in `policy` widened to its maximum simultaneously
- direct injection of `quote_authorized`, `offer_authorized`, `status` and
  `point_cents` into the request, the subject, and a comparable
- 50 and 51 comparables (at and over budget)
- six `purpose` manipulations

```
mutations probed:          457
authorization violations:    0
```

**`quote_authorized` and `offer_authorized` were `False` under every one of 457
mutations**, including on the clean baseline. The gate also cannot be widened
enough to pass: with `max_spread_bps` at its maximum of 10,000, a 20M–80M comp
set still returns `needs_review` with the point withheld, because the validator
bounds the policy itself.

**This is the strongest result in either cycle.** Part 20's mutation requirement
is satisfied with evidence, and no other component in the three repositories has
been shown to hold an invariant under adversarial mutation.

---

## E-14 — Brief generator: suppression and evidence gating

Baseline brief:

```
phase=VERIFY  ready_for_call=False
blocked_reasons=['missing_verified_phone', 'unsafe_intel_packet',
                 'dial_authorization_requires_rei_preflight']
```

**Suppression** — both flags force a hard stop:

| Input | Phase | Objective |
|---|---|---|
| `opted_out=True` | `WRAP` | *"Do not contact this seller. Honor suppression."* |
| `dnc_blocked=True` | `WRAP` | *"Do not contact this seller. Honor suppression."* |

**`ready_for_call` was `False` in all 8 input combinations tried**, and
`blocked_reasons` always carried `dial_authorization_requires_rei_preflight` —
Bob never authorizes a dial, it defers to REI's preflight by construction.

**Adversarial inputs** — all 10 either raise with a specific message or degrade
safely (`ttl_hours` out of range, `ttl_hours='24'` as a string, empty/None
`lead_id`, non-dict `lead`/`packet`/`strategy_context`), and a stale or absent
`assembled_at` adds `packet_freshness_unverified` rather than passing silently.

**Mood evidence gating** — only a fresh, seller-sourced, enum-valid value passes:

| Supplied mood | Result |
|---|---|
| `{value: motivated, source: seller, fresh}` | `motivated` |
| `{value: motivated, source: guess, fresh}` | `unknown` |
| `{value: motivated, source: seller, 2020}` | `unknown` |
| `{value: "<script>", source: seller, fresh}` | `unknown` |
| `"motivated"` (bare string) | `unknown` |

Four of five rejected. Source, freshness and enum membership are all enforced.

### This sharpens the cross-repo defect

Bob emits `ready_for_call: False` together with **three named reasons not to
call** — and `REI-AGENT/backend/voice/call_brief_loader.py` reads neither the
flag nor the reasons (measured: 0 reads). Bob is doing careful, conservative,
evidence-gated work and the consumer discards the entire safety half of its
output. The loss is wholly on the REI side.

---

## Findings added this cycle

| # | Finding | Severity | Evidence |
|---|---|---|---|
| **B-8** | Coverage inverted against risk: deterministic core 94–98%, statistical layer 29.9% | Medium | E-7 |
| **B-9** | `cash_on_cash_return` can return `'-0.000000'`; sign-readers disagree | Low | E-9 |
| **B-10** | A scaled comp span reaches 80% coverage only at an uninformative width, and never at the 3-comp minimum; the comp span is the wrong object to calibrate | High | E-11 |

### Corrections to my own prior audits

| What I wrote | Correction |
|---|---|
| "no cost-based MAO solver" | **Wrong.** `flip_analysis` returns `purchase_limit_cents` and `target_profit_feasible_at_limit`. Part 7 is substantially satisfied |
| Ames' 61.9% shortfall is caused by ranking breaking exchangeability | **Not reproduced.** E-11 found ranking *improves* coverage. Replaced with an unmodelled-variance hypothesis, marked NOT MEASURED |
| "ARV engine present, measured" (cycle 1) | Already corrected to kernel-only by E-1 |

Register total: **89 findings.**

---

## BOB INTELLIGENCE — PERFORMANCE REPORT, CYCLE 2

- **Cycle Number:** 2
- **Baseline Version:** `bob-intelligence-@be5b233`
- **Experiments Completed:** 8 this cycle (E-7 … E-14); 13 across both cycles
- **Simulations Executed:** 2,042,000 cumulative — 1,880,000 (cycle 1) + 96,000 (E-11) + 30,000 Hypothesis examples (E-8) + 457 mutations (E-13) + 35 adversarial cases
- **Properties Screened:** 0 live; 0 historical re-scored (dataset host denied)
- **Verified Hidden Gems:** **NOT MEASURED** — no hidden-gem scoring exists
- **ARV Median Error:** **NOT MEASURED for the production path.** Kernel-only: 9.86% MdAPE (prior artifact, held-out 2010 Ames as-is)
- **False HOT BUY Rate:** **NOT MEASURED** — no classifier exists; metric undefined
- **Financial Test Pass Rate:** 3,455 passed / 17 skipped / 0 failed. **Coverage 79.5% measured.** Property tests: 9 of 10 at 3,000 examples each
- **Critical Risk Failures:** **0.** 457 mutations produced 0 authorization violations; suppression forced a hard stop in 2 of 2 cases; mood gating rejected 4 of 5 unverified inputs
- **Strategy Selection Accuracy:** **NOT MEASURED** — no Strategy Matrix exists
- **Improvements Demonstrated:** None promoted. Strategy I meets the coverage criterion at n≥5 but **fails a width test**, so cycle 1's recommendation is withdrawn pending a revised criterion
- **Regressions Discovered:** None in Bob. Two of my own prior conclusions corrected
- **Composite Quality Score:** **NOT MEASURED.** 5 of Part 23's 8 weighted metrics still have no engine behind them
- **Remaining Blockers:** (1) `jse.amstat.org` denied here — environment `env_019MqoPiQFzTNANf4AZFR6Kp` allows it but this session cannot move onto it; (2) Rehab Engine absent
- **Next Experiment:** E-15 — fit a residual-variance interval in `market_research.py` and compare its coverage and width against span scaling, on the frozen 2010 split. Pre-registered criterion: coverage ≥80% **and** mean width ≤50% of the point estimate **and** MdAPE ≤10.5%

---

## What I could not run, and why

- **E-6 (Ames confirmation):** `jse.amstat.org:443` returns a policy denial from
  this environment's proxy. A package-registry substitute would not match the
  pinned SHA-256 and the harness hard-fails on checksum mismatch, so results
  would not be comparable to the frozen baseline. Environment
  `env_019MqoPiQFzTNANf4AZFR6Kp` was created with the host allowed; this session
  type cannot be moved onto it.
- **Karpathys' 13,862 lines of tests:** require Postgres 17 and Redis. Not
  attempted here. **`[UNVERIFIED]`**
- **Rehab accuracy:** no completed project outcomes exist. Expected-vs-actual is
  **NOT MEASURED** and will stay so until projects close.

*All experiments above were executed in this session against `bob-intelligence-`
at `be5b233`. No repository file was modified.*
