# Bob — Rehab Engine Specification

**Status:** specification only. No implementation authorized or performed.
**Cycle:** 1 · **Date:** 2026-11-07
**Target:** `bob-intelligence-`, new package `backend/rehab/`

---

## 0. Why this engine is Tier 1

Measured in this session, by running Bob's own code:

```python
a = compare_sales({... 'purpose': 'as_is' ...})
b = compare_sales({... 'purpose': 'after_repair', 'renovation_plan_ref': 'plan:x' ...})

a['point_cents'] == b['point_cents']   # True
fields that differ: ['purpose']
```

**`purpose='after_repair'` changes exactly one field — the label.** The point
estimate, supported low and supported high are byte-identical to the as-is
valuation. `compare_sales` accepts no renovation scope, no cost input, and no
post-renovation condition target. It requires a `renovation_plan_ref` token and
never reads anything behind it.

So Bob today produces an "ARV" that is the as-is comparison relabeled.

Downstream, `finance.py` already has the consumer waiting:

```python
screening_mao(arv_cents, repairs_cents, multiplier_bps=7000)
repairs_with_contingency(line_item_cents, contingency_bps)
flip_analysis(..., repairs_cents, ...)
```

`screening_mao` is correct and tested. **Nothing produces its `repairs_cents`
argument.** That one missing input is what blocks the 70% rule, cost-based MAO,
deal grading by acquisition ratio, HOT BUY categorisation, and therefore Part 22
Objective 1 (false HOT BUY rate), which is currently not merely unmeasured but
undefined.

The Rehab Engine is the smallest change that unblocks all of it.

---

## 1. Design constraints inherited from Bob

The spec adopts Bob's existing idioms rather than inventing new ones. These are
observed in `engine.py` and `finance.py`, not proposed:

| Convention | Source |
|---|---|
| Integer cents everywhere; no floats in money | `finance.py` throughout |
| Rates and multipliers in basis points, bounded | `multiplier_bps=7000`, `contingency_bps` |
| `Decimal` with explicit rounding mode; `Fraction` for exact weights | `rounded()`, `reconcile_indications` |
| `integer(value, minimum, maximum)` for every numeric input | `engine.py:15` |
| `token(value)` for every reference string | `engine.py:21` |
| Status enum `needs_data` / `needs_review` / `ready_advisory` | `compare_sales` |
| Withhold the number entirely when review is required | `point=None` unless `not review_reasons` |
| `quote_authorized: False`, `offer_authorized: False` on every output | `compare_sales` return |
| `schema_version` on every contract | `call_brief.py`, `engine.py` |
| Per-item `evidence_ref` and `reviewed_by` | `adjustments` in `compare_sales` |
| Explicit `rejected_*` and `review_reasons` lists | `compare_sales` return |
| No comments in code | `AGENTS.md` |

---

## 2. Scope boundary

**The Rehab Engine estimates renovation scope and cost. It does not value
property and it does not authorize anything.**

| In scope | Out of scope |
|---|---|
| Category-level cost estimation | ARV / valuation (that is `valuation/engine.py`) |
| Low / expected / high bounds | Deal grading (separate engine) |
| Contingency | HOT BUY categorisation (separate engine) |
| Inspection priorities | Scheduling contractors |
| Unknown-condition tracking | Any external communication |
| Confidence and evidence class | Quoting or offering |

---

## 3. Input contract

```
RehabRequest
  schema_version        "1.0"
  subject_id            token
  as_of                 ISO date, not in the future
  living_area_sqft       integer 1..100000
  year_built            integer 1800..current year
  property_type         one of PROPERTY_TYPES (reuse engine.py)
  target_condition      one of CONDITION_TARGETS            § 4
  observations          list[Observation], 0..200            § 5
  cost_basis_ref        token    identifies the cost table and its vintage
  policy                RehabPolicy (optional)               § 8
```

```
Observation
  category              one of REHAB_CATEGORIES              § 6
  condition             one of CONDITION_GRADES              § 5
  evidence_class        VERIFIED | REPORTED | ESTIMATED | ASSUMED | UNKNOWN
  evidence_ref          token
  observed_on           ISO date <= as_of
  reviewed_by           token
  quantity              integer >= 0, optional (sqft, count, linear ft)
  quantity_unit         one of QUANTITY_UNITS, required when quantity present
  note_ref              token, optional
```

**Rule 3.1 — Evidence class is never upgraded.** An `ASSUMED` observation can
never become `REPORTED` or `VERIFIED` inside this engine. Only a new
observation with its own `evidence_ref` and `reviewed_by` can do that.

**Rule 3.2 — A missing category is `UNKNOWN`, not "fine".** Absence of an
observation for `foundation` does not mean the foundation is sound. See § 7.

---

## 4. Condition targets

`CONDITION_TARGETS = {'rent_ready', 'retail_resale', 'full_renovation'}`

The target determines which categories are in the required set and which
finish tier applies. The same property produces different scopes for a rental
hold than for a retail flip, and the engine must not silently assume one.

**Rule 4.1 — The target must match the valuation purpose.** A cost estimate
produced for `rent_ready` must not be combined with an `after_repair` valuation
whose comparables are retail-finish sales. § 11 enforces this at the seam.

---

## 5. Condition grades

`CONDITION_GRADES = {'sound', 'cosmetic', 'worn', 'failed', 'unknown', 'hazard'}`

| Grade | Meaning | Cost treatment |
|---|---|---|
| `sound` | No work required | Zero |
| `cosmetic` | Finish-level work only | Light band |
| `worn` | Functional but near end of life | Medium band |
| `failed` | Must be replaced | Heavy band |
| `unknown` | Not observed | **§ 7 — no point estimate** |
| `hazard` | Suspected environmental or structural hazard | **§ 7 — no point estimate** |

**Rule 5.1 — `hazard` and `unknown` are not costs, they are blockers.** They
never receive an invented dollar figure. Part 6's requirement that "unknown
structural conditions must remain explicitly unknown until properly evaluated"
is implemented as a status, not as a wide range.

---

## 6. Categories

The seventeen Part 6 categories, as a closed set:

```
REHAB_CATEGORIES = {
  'foundation', 'roof', 'electrical', 'plumbing', 'hvac',
  'kitchen', 'bathrooms', 'flooring', 'windows', 'doors',
  'interior_finishes', 'exterior', 'landscaping',
  'permits', 'code_compliance', 'environmental', 'contingency'
}
```

`contingency` is computed, never supplied as an observation. An observation
carrying `category='contingency'` is rejected.

**Structural tier** — `{'foundation', 'roof', 'electrical', 'plumbing', 'hvac',
'environmental', 'code_compliance'}`. These drive the blocking rules in § 7.
A `failed` kitchen is a budget line. A `failed` foundation is a different kind
of fact, and the engine treats them differently.

---

## 7. The blocking rules — deterministic, model cannot override

This is the section that matters most. Part 11 requires hard stops the language
model cannot talk its way past, and `compare_sales` already demonstrates the
pattern: when review is required it returns `point=None`.

| Rule | Condition | Result |
|---|---|---|
| **7.1** | Any structural-tier category is `unknown` | `status='needs_data'`, **no point estimate**, category named in `blocking_unknowns` |
| **7.2** | Any category is `hazard` | `status='needs_review'`, **no point estimate**, `review_reasons += 'suspected_hazard_requires_assessment'` |
| **7.3** | Any `failed` structural category whose only evidence is `ASSUMED` or `REPORTED` | `status='needs_review'`, no point estimate |
| **7.4** | Expected total > `max_rehab_to_arv_bps` of supplied ARV (§ 11) | `review_reasons += 'rehab_exceeds_arv_policy'`, no point estimate |
| **7.5** | High-bound ÷ low-bound > `max_bound_ratio_bps` | `review_reasons += 'estimate_too_uncertain_to_quote'`, no point estimate |
| **7.6** | Fewer than `min_observed_categories` observations present | `status='needs_data'` |
| **7.7** | `cost_basis_ref` vintage older than `max_cost_basis_age_days` | `review_reasons += 'stale_cost_basis'`, no point estimate |

**Rule 7.8 — A withheld estimate still returns the full reasoning.** Bounds,
per-category detail, `blocking_unknowns`, `review_reasons` and inspection
priorities are always returned. Only `expected_total_cents` is withheld. The
operator sees everything the engine knows and does not receive a number the
evidence cannot support.

This mirrors `compare_sales` exactly: `accepted_comparables`, `rejected_comparables`
and `review_reasons` are always populated; `point_cents` is withheld.

---

## 8. Policy

```
RehabPolicy (all basis points or bounded integers, all with defaults)
  contingency_bps              default 1500   range 0..10000
  max_rehab_to_arv_bps         default 4000   range 1..10000
  max_bound_ratio_bps          default 25000  range 10000..100000
  max_cost_basis_age_days      default 180    range 1..730
  min_observed_categories      default 8      range 1..17
  structural_unknown_blocks    default True   bool
```

`policy` keys are validated against this exact set, and an unknown key is
rejected — the same discipline `compare_sales` applies to its own policy
(`set(policy) - {...}` raises).

**Rule 8.1 — Defaults are conservative and documented.** `contingency_bps=1500`
is 15%. That figure is a **starting assumption and is not evidence**; § 13
requires it be calibrated against actual project outcomes before it is treated
as anything more.

---

## 9. Cost basis

The $/sqft bands from Part 6 are screening assumptions, and the spec treats
them as such:

| Tier | Part 6 band | Use |
|---|---|---|
| Light | $15–$25 /sqft | `cosmetic` grades, `rent_ready` target |
| Medium | $25–$50 /sqft | `worn` grades |
| Heavy | $50+ /sqft | `failed` grades, `full_renovation` target |

**Rule 9.1 — Bands live in data, not code.** A `CostBasis` record carries
`basis_ref`, `market_area`, `effective_on`, `source_ref`, and per-category
low/expected/high rates. `backend/valuation/san_joaquin.py` already establishes
the pattern of pinning a regional series by identifier and vintage; the cost
basis follows it.

**Rule 9.2 — National bands are `ESTIMATED`, never `VERIFIED`.** A cost basis
not derived from San Joaquin County contractor evidence is labelled as such and
cannot raise output confidence above `low`.

**Rule 9.3 — Quantity beats square footage when present.** A roof with
`quantity=2200, quantity_unit='sqft_roof'` is priced per unit. Whole-house
$/sqft is the fallback when no quantity is supplied, and the output records
which path produced each line.

---

## 10. Output contract

```
RehabEstimate
  schema_version              "1.0"
  subject_id, as_of, target_condition
  status                      needs_data | needs_review | ready_advisory
  low_total_cents             integer          always returned
  expected_total_cents        integer | None   withheld per § 7
  high_total_cents            integer          always returned
  contingency_cents           integer
  base_total_cents            integer
  bound_ratio_bps             integer
  categories                  list[CategoryLine]
  blocking_unknowns           list[category]
  review_reasons              sorted list
  inspection_priorities       ordered list[InspectionPriority]
  confidence                  high | medium | low
  evidence_summary            counts by evidence_class
  cost_basis_ref, cost_basis_effective_on
  method                      'category_condition_cost_basis'
  quote_authorized            False
  offer_authorized            False
```

```
CategoryLine
  category, condition, evidence_class, evidence_ref, reviewed_by
  low_cents, expected_cents, high_cents
  rate_applied_cents_per_unit, quantity, quantity_unit
  pricing_path   'quantity' | 'living_area_sqft'
  excluded       bool
  exclusion_reason   token | None
```

```
InspectionPriority
  rank, category, reason, blocks_estimate (bool), estimated_cost_to_resolve_cents | None
```

**Rule 10.1 — `expected_total_cents` is the only field the 70% rule may
consume**, and only when `status == 'ready_advisory'`. § 11 enforces this.

**Rule 10.2 — Totals are reconciled, not summed independently.**
`base_total_cents == sum(expected_cents for non-excluded lines)`, and
`low_total <= expected_total <= high_total` must hold. A violation raises rather
than returning an inconsistent estimate. This is the invariant Bob's existing
`test_valuation_stress.py` style of testing is well suited to prove.

---

## 11. The seam to valuation and MAO

Three integration rules, each of which closes a defect this audit measured.

**Rule 11.1 — `after_repair` valuation requires a ready estimate.**
`compare_sales` with `purpose='after_repair'` must take a
`renovation_plan_ref` that resolves to a `RehabEstimate` with
`status == 'ready_advisory'`, and must reject the request otherwise. This is the
fix for finding B-4. Today the reference is a token that nothing dereferences.

**Rule 11.2 — Condition target must match comparable finish.** An
`after_repair` valuation whose `target_condition='rent_ready'` must not accept
comparables attested as retail-finish sales. Mismatch →
`review_reasons += 'renovation_target_does_not_match_comparable_finish'`.

**Rule 11.3 — MAO is computed from a tuple, never from two loose numbers.**

```
screening_mao(arv_cents = valuation.point_cents,
              repairs_cents = rehab.expected_total_cents,
              multiplier_bps = 7000)
```

permitted only when **both** `valuation.status == 'ready_advisory'` **and**
`rehab.status == 'ready_advisory'`. If either withholds its number, MAO is
`None` and the deal status is `NEEDS VERIFICATION` — never a grade.

This is what makes Part 8 grading and Part 18 categorisation safe to build: the
acquisition ratio `(purchase + repairs) / ARV` can only be formed from two
numbers that each passed their own gate.

---

## 12. Test plan

Bob's existing standard is an exact oracle plus permutation invariance. The same
standard applies here.

**Exactness and invariance**

1. `base_total == sum(expected)` exactly, over randomized category sets, using
   `Fraction` as the oracle for contingency so there is no rounding drift.
2. Output invariant to observation order, across `permutations` of the
   observation list — the same property `test_valuation_stress.py` proves for
   comparables.
3. No input mutation, verified by `deepcopy` comparison.
4. All money integral; no `float` reaches any output field.
5. `low <= expected <= high` on every line and on the total.

**Blocking rules — one test per rule in § 7**

6. Each structural category `unknown` individually blocks (7 tests).
7. `hazard` in any category blocks, including non-structural.
8. `failed` structural with `ASSUMED`-only evidence blocks; with `VERIFIED`
   evidence it does not.
9. Rehab exceeding the ARV policy blocks.
10. Bound ratio exceeding policy blocks.
11. Stale cost basis blocks.
12. **Degraded state never widens authority** — for every blocking rule,
    `quote_authorized` and `offer_authorized` remain `False` and
    `expected_total_cents` is `None`. This is the mutation test Part 20
    demands: removing or corrupting any field must not increase what the engine
    permits.

**Adversarial — Part 20, mirroring the battery run in this audit**

13. Unknown structural condition presented as `sound` with `ASSUMED` evidence.
14. A `$0` observation on a `failed` category. *(Direct analogue of measured
    finding B-3: in `compare_sales`, a `$0` living-area adjustment passes while
    an honest adjustment triggers review. The Rehab Engine must not repeat it —
    a `failed` grade with a zero cost line is rejected, not accepted.)*
15. Duplicate category observations.
16. Observation dated after `as_of`.
17. Quantity unit mismatched to category.
18. Contingency supplied as an observation.
19. Unknown policy key.
20. Cost basis from the wrong market area.

**Calibration**

21. Expected total vs actual project cost, once outcomes exist. Until then this
    is explicitly **NOT MEASURED** and the engine's confidence may not exceed
    `medium`.

---

## 13. What this spec deliberately does not claim

- **The $/sqft bands are not validated.** They are Part 6's screening
  assumptions. No San Joaquin County contractor evidence has been collected, so
  every estimate from a national band is `ESTIMATED` and caps confidence at
  `low` (Rule 9.2).
- **`contingency_bps=1500` is not calibrated.** It is a documented default
  awaiting outcome data (Rule 8.1).
- **No accuracy target is stated.** Part 22 sets ARV targets; it sets none for
  rehab. Inventing one would be the thing Part 31 warns against. The first
  honest metric is expected-vs-actual on completed projects, and there are none.
- **This does not make Bob able to grade deals.** It unblocks grading by
  supplying `repairs_cents`. Parts 8 and 18 remain absent and are separate work.

---

## 14. Acceptance criteria

The engine is complete when all of the following hold, each independently
checkable:

1. `backend/rehab/` exists with no comments, no floats in money, all inputs
   bounded by `integer()`/`token()`.
2. All 21 test groups in § 12 pass, including permutation invariance and the
   mutation test.
3. `compare_sales(purpose='after_repair')` **rejects** a request whose
   `renovation_plan_ref` does not resolve to a ready estimate — demonstrated by
   a test that the current code fails (B-4 regression guard).
4. `screening_mao` is reachable end to end from a `RehabEstimate` plus a
   `compare_sales` result, and returns `None` when either withholds.
5. Every blocking rule in § 7 has a test proving `quote_authorized is False` and
   `expected_total_cents is None`.
6. A documented cost basis record exists for at least one San Joaquin market
   area, with `source_ref` and `effective_on`.
7. The engine never returns `expected_total_cents` with
   `status != 'ready_advisory'`.

---

*Specification only. Nothing in this document has been implemented. Findings
B-3 and B-4 referenced above were measured in this session by executing Bob's
own `compare_sales`; see `BOB_EXPERIMENT_LOG.md`.*
