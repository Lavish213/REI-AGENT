# Bob — Experiment Log, Cycle 1

**Date:** 2026-11-07 · **Baseline:** `bob-intelligence-@be5b233`
**Mode:** read-only. Bob's code was *executed*, never modified. Scripts were
written to a scratch directory outside all repositories.

Every number below was produced by a command run in this session. Nothing is
estimated or recalled.

---

## Experiment ledger

| ID | Experiment | Result | Severity |
|---|---|---|---|
| **E-1** | Which code path does the published benchmark measure? | **The benchmark measures `reconcile_indications`, not the production `compare_sales` path** | **Critical** |
| **E-2** | Part 20 adversarial battery, 18 cases | 16 fail closed correctly; 2 findings | — |
| **E-3** | Quantify feature-divergence and ARV findings | B-3 and B-4 confirmed with numbers | High |
| **E-4** | Interval coverage: 10 strategies × 2 dispersion regimes × 20,000 trials | Strategy I reaches 81.3% coverage; Bob's current reaches 66.2% | High |
| **E-5** | Is coverage capped by comp count? 9 counts × 200,000 trials | **Law confirmed to within 0.1%: coverage = (n−1)/(n+1)** | **Critical** |

---

## E-1 — The benchmark does not measure the production path

**Method:** constructed comparables shaped exactly as
`scripts/benchmark_valuation.py::record()` produces them (`verified: False`,
`arms_length: None`, no `adjustments`, no `comparison_review_ref`,
no `contract_on`, no `distance_meters`) and passed them through both paths.

```
compare_sales  (production)   status=needs_data   point=None   accepted=0  rejected=5
                              reject reasons: ['malformed_or_unsupported_evidence']
reconcile_indications (bench) point=19000000
```

The published artifact already records this, in a field easy to read past:

```json
"strict_bob_advisory_prices": 0
```

Zero. For both years. Across all 649 held-out subjects, the production valuation
path produced **no advisory price at all**. The 9.86% MdAPE headline is the
accuracy of `reconcile_indications` — the inverse-distance weighting kernel —
measured in isolation.

**Why this matters.** The kernel result is real and well controlled. But it is
evidence about a *component*, not about the system. Two things remain unmeasured
and are easy to assume away:

- How often `compare_sales` reaches `ready_advisory` on real San Joaquin
  evidence. **NOT MEASURED.** It depends entirely on whether incoming data
  carries `verified`, `arms_length`, `comparison_review_ref`, `contract_on`, and
  per-category adjustments with `evidence_ref` and `reviewed_by`.
- Whether the kernel's accuracy survives the gate. The gate changes the comp
  set — it rejects and it requires adjustments that shift adjusted values — so
  the 9.86% does not transfer unchanged.

The artifact's own assumption list says *"strict Bob withholds all prices."*
That line is doing a lot of work and deserves to be in the headline rather than
item eight of thirteen.

**Correction to my own prior audit.** `BOB_INTELLIGENCE_AUDIT.md` reported
9.86% MdAPE under "ARV engine: present, measured." That is too generous. The
engine is present; the *kernel* is measured. The engine's production behaviour
is not.

---

## E-2 — Part 20 adversarial battery

**Method:** built a comparable that passes every gate (verified, arms-length,
closed, reviewed, with `market_time` and `concessions` adjustments), established
a clean 3-comp baseline at `ready_advisory`, then perturbed one input per case.

Baseline: `status=ready_advisory point=39500000 accepted=3 rejected=0`

| Case | Perturbation | Status | Point | Verdict |
|---|---|---|---|---|
| A-1 | Inflated comp, 3× the others | `needs_review` | withheld | ✅ |
| A-2 | Stale sale, 700d vs 365 policy | `needs_data` | withheld | ✅ |
| **A-3** | **Comp 4000 sqft vs 1500 subject** | **`ready_advisory`** | **$397,622** | ⚠️ **finding B-3** |
| A-4 | Duplicate property / sale id | `needs_data` | withheld | ✅ |
| A-5 | Subject used as its own comp | `needs_data` | withheld | ✅ |
| A-6 | Unverified comp | `needs_data` | withheld | ✅ |
| A-7 | Non arms-length sale | `needs_data` | withheld | ✅ |
| A-8 | Pending, not closed | `needs_data` | withheld | ✅ |
| A-9 | Future-dated sale | `needs_data` | withheld | ✅ |
| A-10 | Outside distance policy | `needs_data` | withheld | ✅ |
| A-11 | Positive concession adjustment | `needs_data` | withheld | ✅ |
| A-12 | Missing concession adjustment | `needs_data` | withheld | ✅ |
| A-13 | Incompatible property type | `needs_data` | withheld | ✅ |
| A-14 | Wide dispersion, $200k–$800k | `needs_review` | withheld | ✅ |
| A-15 | Gross adjustment 39% of price | `needs_review` | withheld | ✅ |
| A-16 | Only two comps | `needs_data` | withheld | ✅ |
| A-17 | Different market, no location adj | `needs_data` | withheld | ✅ |
| A-18 | Different market, location adj present | `ready_advisory` | $391,667 | ✅ correct |
| A-19 | `after_repair` without plan ref | raises `KeyError` | — | ✅ |
| **A-20** | **`after_repair` with plan ref** | **`ready_advisory`** | **identical to as-is** | ⚠️ **finding B-4** |

**16 of 18 perturbations fail closed, and the authorization invariant held in
every single case** — `quote_authorized` and `offer_authorized` were `False`
throughout, including on the clean baseline. That is a genuinely strong result
and it should be said plainly: this engine's refusal behaviour is better than
anything else in the three repositories.

Two observability notes, low severity: A-11 and A-17 both surface as the generic
`malformed_or_unsupported_evidence` because an internal `ValueError` /`KeyError`
is caught by the blanket handler at `engine.py:164`. The rejection is correct;
the *reason* loses its specificity, which will make production triage harder.

---

## E-3 — Findings B-3 and B-4, quantified

### B-3 — No feature-divergence ceiling, and a perverse adjustment incentive

Part 5 specifies comparables with "square footage within ±20%". No policy key
enforces it: `compare_sales` has `max_age_days`, `max_distance_meters`,
`max_gross_adjustment_bps` and `max_spread_bps`, and nothing for feature
divergence.

Subject 1500 sqft; one comp's size varied; `living_area` adjustment $0 throughout:

| Comp sqft | Divergence | Status | Point | vs clean |
|---|---|---|---|---|
| 1,800 | +20% | `ready_advisory` | $395,455 | +0.12% |
| 3,000 | +100% | `ready_advisory` | $396,829 | +0.46% |
| 4,000 | +167% | `ready_advisory` | $397,622 | +0.66% |
| 10,000 | +567% | `ready_advisory` | $399,848 | +1.23% |
| **50,000** | **+3233%** | **`ready_advisory`** | **$401,844** | **+1.73%** |

**Being fair to the design:** the weighting kernel divides by
`1 + |area − comp_area| / area`, so a 50,000 sqft comp earns a near-zero weight
and moves the estimate only 1.73%. The damage is bounded by good kernel design.

**The finding is that it is silent.** No `review_reason` fires. An operator sees
`ready_advisory` on a comp set that would fail a Part 5 screen outright, with
nothing in the output saying so.

The sharper half:

| `living_area` adjustment on the 4000 sqft comp | Status | Point |
|---|---|---|
| **$0** | **`ready_advisory`** | **$397,622** |
| −$50,000 | `needs_review` | withheld |
| +$200,000 | `needs_review` | withheld |

**A $0 adjustment passes. An honest adjustment triggers review.** The gate
checks that a required adjustment *category is present*, not that its amount is
plausible — and because a real adjustment moves the adjusted value away from the
other comps, it trips the dispersion gate. The incentive points the wrong way.

### B-4 — `after_repair` is `as_is` relabeled

```
as_is         point=39500000  low=38000000  high=41000000
after_repair  point=39500000  low=38000000  high=41000000
identical point estimate: True
fields that differ between the two results: ['purpose']
```

`compare_sales` requires `renovation_plan_ref` to be a valid token and never
dereferences it. It accepts no renovation cost, no scope, and no
post-renovation condition target. Part 5 requires After Repair Value; the engine
produces an as-is comparison with a different label.

This is the gap `BOB_REHAB_ENGINE_SPEC.md` § 0 and Rule 11.1 exist to close.

---

## E-4 — Interval coverage, 10 strategies

**Method:** synthetic neighborhood, lognormal prices, 5 comps, 20,000 trials per
regime, point estimate from Bob's actual `reconcile_indications`. This is a
**mechanism experiment, not an Ames replication** — the Ames host
(`jse.amstat.org`) is denied by this environment's network policy, so the
checksummed dataset could not be fetched here.

σ = 0.18 (MdAPE 13.39%):

| Strategy | Coverage | Mean width |
|---|---|---|
| **A — raw min/max of comps (Bob today)** | **66.2%** | 41.4% |
| B — point ± 1.0σ | 58.5% | 33.6% |
| C — point ± 1.5σ | 75.4% | 50.4% |
| D — point ± 2.0σ | 85.0% | 67.2% |
| E — point ± 2.5σ | 91.0% | 84.0% |
| F — point ± 3.0 MAD | 74.4% | 58.2% |
| G — union(span, ±1.5σ) | 76.1% | 51.4% |
| H — union(span, ±2.0σ) | 85.0% | 67.2% |
| **I — raw span widened 1.5× about the point** | **81.3%** | **62.1%** |
| J — raw span widened 2.0× about the point | 89.3% | 82.9% |

σ = 0.25 (MdAPE 18.62%): strategy A is **66.2% again**. Width scales with
dispersion; **coverage does not move at all.** That invariance is the clue that
led to E-5.

**Against the promotion criterion** I set in the prior audit (coverage ≥80%,
MdAPE ≤10.5%, bias within ±1%): strategy **I** is the cheapest qualifying
change. It reuses the span already computed at `engine.py:168-169` and scales it
about the point estimate — no new statistic, no new input. Strategies D and H
reach 85% but cost ~5 points more width.

**Caveat stated plainly:** these coverage figures come from synthetic draws.
They establish the *mechanism* and rank the strategies. They do not replace the
Ames measurement, which must be re-run on the checksummed dataset before any
change is promoted.

---

## E-5 — Coverage is capped by comparable count, not by accuracy

**Hypothesis:** for `n` exchangeable draws, the probability that an independent
draw falls within the min/max of those `n` is exactly `(n−1)/(n+1)`.

**Method:** 200,000 trials at each of 9 comp counts.

| n comps | Predicted | Observed | Δ |
|---|---|---|---|
| 3 | 50.00% | 49.90% | −0.10% |
| 4 | 60.00% | 60.09% | +0.09% |
| **5** | **66.67%** | **66.67%** | **0.00%** |
| 6 | 71.43% | 71.41% | −0.02% |
| 7 | 75.00% | 75.02% | +0.02% |
| **9** | **80.00%** | **80.01%** | **+0.01%** |
| 11 | 83.33% | 83.26% | −0.08% |
| 15 | 87.50% | 87.44% | −0.06% |
| 19 | 90.00% | 90.02% | +0.02% |

Confirmed to within 0.1% at every count. It is a distribution-free
order-statistic result, which is why E-4 saw identical coverage at both σ.

**What this means for Bob.** While `supported_low/high` are defined as the raw
min/max of accepted comparables, coverage is structurally bounded:

| Bob's comp count | Coverage ceiling |
|---|---|
| 3 (the enforced minimum) | **50.0%** |
| 5 (the benchmark's count) | **66.7%** |

Comps required to reach a target, using raw min/max:

| Target | Comps needed |
|---|---|
| 70% | 6 |
| 75% | 7 |
| **80%** | **9** |
| 85% | 13 |
| 90% | 19 |

**This reframes finding B-2 entirely.** I previously called the interval
"miscalibrated" and noted it had regressed against the random baseline. Both
observations were accurate, but the diagnosis was wrong. The interval is not
badly calibrated — it is **not a calibrated interval at all**, and no
improvement in valuation accuracy can raise its coverage. Either the definition
changes (strategy I), or nine accepted comparables are required, which a thin
Stockton submarket will rarely supply.

The engine's own field name has been telling the truth the whole time:

```
'range_meaning': 'observed_adjusted_sale_span_not_statistical_confidence_interval'
```

It is honest. The problem is that a 50–67%-coverage span presented beside a
single-digit MdAPE invites a reader to treat it as a confidence interval, and
Part 5 asks for "a supported valuation range and confidence assessment."

**Why real Ames measured 61.9%, below the 66.7% ceiling:** comps are chosen by
`rank_candidates` for similarity to the subject, which makes them more similar
to *each other* than to the subject. That breaks exchangeability in the
direction that narrows the span. The ranking that improves the point estimate
is the same mechanism that degrades the interval.

---

## Findings carried into the register

| # | Finding | Severity | Evidence |
|---|---|---|---|
| **B-5** | Published 9.86% MdAPE measures the weighting kernel, not the production valuation path, which produced **zero** advisory prices across 649 held-out subjects | **Critical** | E-1 |
| **B-6** | Interval coverage is combinatorially capped at `(n−1)/(n+1)`: 50% at Bob's 3-comp minimum, 66.7% at 5 | **Critical** | E-5 |
| **B-3** | No feature-divergence policy ceiling; a +3233% sqft comp yields `ready_advisory` silently, and a $0 adjustment passes where an honest one triggers review | High | E-3 |
| **B-4** | `purpose='after_repair'` differs from `as_is` in the label only; no renovation input is accepted | High | E-3 |
| **B-7** | Rejection reasons collapse to `malformed_or_unsupported_evidence` for `ValueError`/`KeyError` cases, losing triage specificity | Low | E-2 |

Register total across all documents: **86**.

---

## BOB INTELLIGENCE — PERFORMANCE REPORT, CYCLE 1

- **Cycle Number:** 1
- **Baseline Version:** `bob-intelligence-@be5b233`
- **Experiments Completed:** 5 (E-1 … E-5)
- **Simulations Executed:** 1,880,000 — 40,000 (E-4) + 1,800,000 (E-5). Adversarial cases: 20
- **Properties Screened:** 0 live. 0 historical re-scored this cycle (dataset host denied)
- **Verified Hidden Gems:** **NOT MEASURED** — no hidden-gem scoring exists
- **ARV Median Error:** **NOT MEASURED for the production path.** Kernel-only, from the prior artifact: 9.86% MdAPE on held-out 2010 Ames as-is prices
- **False HOT BUY Rate:** **NOT MEASURED** — no HOT BUY classifier exists; metric undefined
- **Financial Test Pass Rate:** 3,455 passed / 17 skipped / 0 failed, executed in this session
- **Critical Risk Failures:** 0 in Bob's own suite. 2 new critical audit findings (B-5, B-6); the authorization invariant held in all 20 adversarial cases
- **Strategy Selection Accuracy:** **NOT MEASURED** — no Strategy Matrix exists
- **Improvements Demonstrated:** None promoted. Strategy I identified as meeting the pre-registered promotion criterion in synthetic testing; it is **not** promoted because the Ames confirmation could not be run here
- **Regressions Discovered:** None introduced. Two pre-existing properties correctly re-diagnosed (B-2 → B-6)
- **Composite Quality Score:** **NOT MEASURED.** 5 of Part 23's 8 weighted metrics have no engine behind them
- **Remaining Blockers:** (1) `jse.amstat.org` denied in this environment — environment `env_019MqoPiQFzTNANf4AZFR6Kp` was created with that host allowed, but this session cannot move onto it; (2) Rehab Engine absent → MAO, grading and HOT BUY unreachable
- **Next Experiment:** E-6 below

---

## E-6 — the next experiment, pre-registered

**Hypothesis:** interval strategy I (raw span widened 1.5× about the point)
raises held-out 2010 Ames coverage from 61.9% to ≥80% without moving MdAPE past
10.5% or bias outside ±1%.

**Why pre-register:** the 2010 set is already frozen. Writing the criterion down
before the run is what stops it becoming a search for a number that looks good.

**Frozen baseline:** MdAPE 9.86%, coverage 61.9%, bias +0.37%, n=215.

**Promotion criterion:** coverage ≥80% **and** MdAPE ≤10.5% **and** |bias| ≤1%.
Report the full trade-off curve for strategies A, C, D, I and J either way.

**Leakage control:** any tuning on 2009 only; 2010 scored once.

**Exact command, once the dataset is reachable:**

```
curl -o AmesHousing.txt https://jse.amstat.org/v19n3/decock/AmesHousing.txt
sha256sum AmesHousing.txt   # must equal 6cfe6cb5...e67cfcc
python3 scripts/benchmark_valuation.py AmesHousing.txt --output /tmp/coverage-run.json
```

The harness already records `observed_comp_span_contains_sale`, so coverage is
measurable without modifying Bob — only the interval definition under test needs
to vary, and that can be done in a scratch copy.

**To unblock:** start a session on environment
`env_019MqoPiQFzTNANf4AZFR6Kp` ("San Joaquin REI (valuation research)"), which
allows `jse.amstat.org`. It is created and saved for all three repositories.

---

*All five experiments were executed in this session. Bob's code was imported and
run; no file in any repository was modified. Scripts live in this session's
scratch directory and are not committed.*
