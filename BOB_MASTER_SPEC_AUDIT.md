# Bob Intelligence — Master Spec Audit (PART A–G)

Date: 2026-11-08
Spec: BOB INTELLIGENCE — ULTIMATE MASTER SYSTEM PROMPT, Master Architecture Specification V1
Audited repository: `lavish213/bob-intelligence-` @ `claude/project-visibility-8cah98`
Method: direct inspection of all 31 Python modules. No capability is reported as
present unless it was read in the source.

Per Section 42 this document contains **no implementation code** and requests
approval before further changes. Section 39's Gate 1 is identified in PART G.

**Update 2026-11-08.** Work authorised after this audit has closed part of it.
Section 22 is now implemented, `backend/scoring/` is no longer empty, and Bob's
grading is wired through to the Karpathys dashboard. The table in PART C and the
`scoring/` finding in A.5 are corrected in place below; everything else stands.

---

## PART A — Existing System Audit

### A.1 What Bob actually is

Bob is a **narrow, deep, unusually well-engineered valuation and call-brief
service**. It is not an acquisition platform. 799 lines of valuation code and
3,482 passing tests sit behind one strong idea: a gated, evidence-adjusted sales
comparison engine that refuses to produce a number it cannot defend.

That framing matters because measured against this 42-section spec Bob implements
roughly **10–15%** of the surface — but the part it implements is closer to
appraisal-grade than most commercial products, and almost none of it is the kind
of code worth replacing.

### A.2 Actual module tree (31 files, verified)

```
backend/
  valuation/     engine.py 207   finance.py 77      local_benchmark.py 127+
                 market_research.py 195             candidates.py 50
                 san_joaquin.py 72                  california.py 37
                 __main__.py 30
  call_planner/  brief_generator.py  objective_selector.py  checkbox_selector.py
                 avoidances_builder.py               escalation_rules.py
  contracts/     call_brief.py 30
  db/            client.py (11 functions)
  events/        bob_events.py 37
  decisions/     decision_logger.py
  worker/        loop.py 70
  scoring/       __init__.py  ← EMPTY (0 lines)
  intel/         __init__.py  ← EMPTY (0 lines)
  config.py   health.py   main.py
```

### A.3 What works, and works well

| Capability | Evidence |
|---|---|
| Evidence-adjusted sales comparison | `engine.compare_sales`, 12 accept/reject gates |
| Per-adjustment provenance | every adjustment needs `evidence_ref` + `reviewed_by` |
| Mandatory adjustment coverage | required categories derived from subject/comp feature diff |
| Comparability bounds | line cap, area divergence, distance, age, gross, spread |
| ARV/as-is separation | `purpose` gate; after-repair rejects non-renovated comps |
| Exact arithmetic | `Decimal`/`Fraction`, integer cents, no floats in money |
| Refusal as output | `quote_authorized`/`offer_authorized` always `False`; reasoned rejections |
| Profit-based MAO solve | `flip_analysis` solves `/(1 + buy_rate)` then integer-searches for rounding |
| Honest interval labelling | `observed_adjusted_sale_span_not_statistical_confidence_interval` |
| Ratio-study metrics | median/mean/weighted ratio, COD, PRD, PRB + IAAO flags |
| Output drift gate | 12-scenario matrix vs committed baseline, verified to fail |
| Local obligation encoding | `san_joaquin.py` — FIPS 06077, real parcel authority, 7 review items |
| Sophia strategy packets | `call_planner/` + `contracts/call_brief.py` |
| Test discipline | 3,482 passing, 17 skipped, ruff clean |

### A.4 What is incomplete

- **`market_research.py`** — the only statistical model in the repo. Has conformal
  machinery (`calibration_radius(scores, alpha_bps)`) but returns a **single global
  radius** (constant width), and sits at **29.9% coverage**. Effectively unvalidated.
- **`finance.py`** — 8 functions against Section 12's ~90 formulas. `flip_analysis`
  self-documents its own limit: `cost_model: fixed_holding_and_financing_inputs_
  must_be_recomputed_if_purchase_or_term_changes`. The purchase-limit solve is exact
  for buy-side basis points but **not** for financing that scales with loan amount.
- **`candidates.py`** — advisory ranker only, `status: candidate_review_only`.
- **`local_benchmark.py`** — correct, but has no cohort to run against.

### A.5 What is absent

`backend/intel/` is an **empty file** — a declared namespace with zero
implementation.

`backend/scoring/` was the same when this audit was written. It now contains
`opportunity.py`, implementing Section 22: a deterministic, versioned grade with
economics and evidence confidence held as independent axes, readiness derived from
both, explicit unknown states instead of zero substitution, and a lockout class.
It is reached through `brief.evidence.opportunity` and surfaced by the
`bob_opportunity_overview` RPC.

More consequentially: Bob has **no data acquisition layer at all**. No provider
client, no ingestion, no property identity resolution. `compare_sales` consumes
comparables that someone else must supply, pre-attested, and says so:
`evidence_verification: trusted_input_attestations_not_independent_source_research`.

---

## PART B — Elite Professional Research

Carried out this session and in `OPEN_SOURCE_COMPARISON.md` / `VALUATION_RESEARCH.md`.
Condensed to what bears on implementation.

### B.1 Methodology findings that Bob should adopt

| Source | Finding | Bearing on Bob |
|---|---|---|
| Freddie Mac Seller/Servicer Guide §5605.6 | ≥3 closed comps, within 12 months | Bob requires ≥3 ✓; 180d is tighter ✓ |
| Appraisal practice | good selection makes adjustments *fewer and smaller* | motivates the gates, not just the adjustments |
| Appraisal-QC patent | flag any single line adjustment >10% of comp price | shipped as `max_line_adjustment_bps` |
| IAAO Standard on Ratio Studies | COD ≤15 residential, PRD 0.98–1.03, PRB ±0.05 | shipped in `summarize()` |
| Cook County `model-res-avm` | **CI fails when model output moves** | shipped as the drift gate |
| Cook County | LightGBM, ~100 features, **no comps at all**; excludes condition | Bob is the inverse; complementary, not behind |
| Cook County (unused) | comp similarity from **LightGBM leaf co-occurrence** | cheap spike, no new data needed |
| Retrieval-Enhanced Appraisal `[secondary]` | comp *selection* policy is "relatively naive" in all models | describes Bob's hard thresholds exactly |
| Conformal literature | constant-width intervals fail at both price extremes | Bob's `calibration_radius` is exactly this |
| PySAL `mgwr`/`spreg` | GWR fits a local relationship per location | replaces opaque `market_area` token equality |
| RSMeans (vendor) | square-foot models are "conceptual / ballpark" | Section 11 bands must be labelled assumptions |
| Practitioner consensus | **stacked** distress signals beat any single list | already in REI-AGENT's scorer |
| Practitioner consensus | best signals carry an **externally imposed deadline** | pre-FC, probate, tax delinquency |

### B.2 Benchmarks to measure against

| Metric | Reference |
|---|---|
| Zillow off-market median error | ~7.01% `[secondary]`, 4.5% NV to 12.7% VT |
| Zillow on-market median error | ~1.83% `[secondary]` |
| Bob measured error | 9.86% |
| Zillow Prize winner | beat Zestimate ~13%, below 4% |
| Direct mail response | 0.5–2%; 2–5% fresh probate/pre-FC |
| Cold call | 12–18% contact of dials; 800–1,200 dials/deal |
| Cost per signed contract | ~$2,300 national survey |

Off-market is the correct comparison, since distressed sellers are by definition
not on-market. **9.86% against ~7% is respectable**, and Section 31's implicit
"beat the professionals" goal needs that context: a few points behind a company
with a national data moat is not failure.

### B.3 Where expert methods conflict, and the resolution

1. **Fixed radius vs competitive market.** Freddie leans on proximity; Bob's own
   docs say "use competitive market... rather than a fixed radius alone."
   *Resolved:* keep the radius as a cheap screen, treat submarket as the real
   boundary once GWR exists (§5.8 of the comparison doc).
2. **70% rule vs profit-based underwriting.** Section 13 says the heuristic
   "must not automatically become the final offer." Bob has both — `screening_mao`
   and `flip_analysis`. *Resolved:* already correct in Bob; the conflict is with
   REI-AGENT's `AGENTS.md`, see D.3.
3. **Adjustment ceilings.** Fannie Mae sets no universal net/gross ceiling. Bob's
   30% gross, distance and area bands are explicitly "internal screening choices,
   not appraisal rules." *Resolved:* keep that labelling on every new threshold.

---

## PART C — Complete Capability Gap Analysis

All 42 sections. Status is from source inspection.

| § | Capability | Status | Evidence / gap |
|---|---|---|---|
| 1 | Research elite methods | **DONE** | this doc + 2 research docs |
| 2 | Repository audit | **DONE** | PART A |
| 3 | Three-system architecture | **PARTIAL** | Bob↔Sophia via `call_brief`; Karpathys via `bob_events`; no routing authority in Bob |
| 4 | Locked module structure | **ABSENT** | `coordinator/`, `engines/`, `memory/` do not exist. See D.1 |
| 5 | Continuous deal radar | **ABSENT** | no listing/distress monitoring in Bob |
| 6 | Property identity & ownership | **ABSENT** | no APN resolution, no deed/ownership records, no dedup |
| 7 | Elite comparable engine | **STRONG** | best component; see A.3 |
| 8 | Full valuation intelligence | **PARTIAL** | sales comparison strong; `cost_approach` + `rental_analysis` basic; **no reconciliation**, no DCF |
| 9 | Hyperlocal market intelligence | **MINIMAL** | `index_ratio` exists, unwired; none of the 28 listed indicators |
| 10 | Visual condition intelligence | **ABSENT** | no imagery handling |
| 11 | Advanced rehab engine | **MINIMAL** | only `repairs_with_contingency`; none of the 27 line items, no cost bands |
| 12 | Complete math engine | **PARTIAL ~20%** | see PART E |
| 13 | MAO engine | **GOOD** | both methods; honest about fixed-cost limit |
| 14 | Buyer demand & exit | **ABSENT** | no buyer profiles in Bob |
| 15 | Seller signal intelligence | **ELSEWHERE** | implemented in REI-AGENT `scout/scorer.py`, not Bob |
| 16 | Knowledge graph | **ABSENT** | no graph store |
| 17 | Hidden value / development | **ABSENT** | no zoning/ADU/lot-split analysis |
| 18 | Title & transaction feasibility | **ABSENT** | `san_joaquin.REVIEW_ITEMS` names 7 risks but performs no research |
| 19 | Strategy matrix | **ABSENT** | none of the 14 strategies modelled |
| 20 | Negotiation intelligence | **PARTIAL** | `call_planner/` produces objectives/avoidances, not negotiation plans |
| 21 | Multi-scenario simulation | **ABSENT** | no conservative/base/optimistic, no stress tests |
| 22 | Opportunity scoring & grading | **IMPLEMENTED** | `scoring/opportunity.py`; A–F grade, HOT BUY / WATCH LIST / ARCHIVED, evidence-capped |
| 23 | Lockout / early rejection | **PARTIAL** | engine rejects comps; deal-level `lockout_class` now distinguishes blocked, permanent, research-required and price-dependent; no reopen trigger yet |
| 24 | Opportunity cost engine | **ABSENT** | no research prioritisation |
| 25 | Speed / staged funnel | **ABSENT** | no stages, no caching, no latency budget |
| 26 | Provider & source intelligence | **ABSENT** | no provider layer to evaluate |
| 27 | Active research agent | **ABSENT** | no research loop |
| 28 | Fraud & data integrity defense | **PARTIAL** | strong input validation + dedup in engine; no injection isolation for retrieved text |
| 29 | Memory & continuity | **PARTIAL** | `decision_logger`, DB tables; no `memory/`, no versioned historical conclusions |
| 30 | Self-improvement | **ABSENT** | nothing tracks predicted vs actual outcomes |
| 31 | Professional benchmarking | **PARTIAL** | `local_benchmark.py` is a real harness with no cohort |
| 32 | Sophia integration | **GOOD** | `call_brief` contract + brief generator + suppression override |
| 33 | Due diligence & closing | **ABSENT** | no deadline tracking |
| 34 | Compliance & governance | **PARTIAL** | `quote/offer_authorized: False` everywhere; no licensing/fair-housing/DNC layer in Bob |
| 35 | Observability & reliability | **MINIMAL** | grade freshness now exposed so a stalled worker is visible; still no tracing, circuit breakers or idempotency |
| 36 | Testing requirements | **STRONG** | 3,482 tests; drift gate; exact oracles |
| 37 | Property intelligence report | **PARTIAL** | the deal row now carries identity, ARV, asking, purchase limit, headroom, evidence confidence, signals, contradictions, risks and next action; rehab, market and strategy sections remain absent |
| 38 | 30 research deliverables | **THIS DOC** | |
| 39 | Implementation priority | **PART F** | |
| 40 | Absolute engineering rules | **OBSERVED** | see D.1/D.3 for the two conflicts |
| 41 | Intelligence doctrine | **PARTIAL** | the engine embodies the skepticism; no deal-level loop |

**Summary at audit time: 5 strong/good, 10 partial, 1 elsewhere, 20 absent.**
**After the authorised follow-up work: 6 strong/good/implemented, 11 partial, 1 elsewhere, 18 absent.**

---

## PART D — Production Architecture Plan

### D.1 Conflict: Section 4 vs Section 2 and Rule 40.2

Section 4 names a canonical tree (`coordinator/`, `engines/`, `memory/`,
`contracts/`) and calls it "locked." **None of it exists.** Meanwhile Section 2
says "preserve the existing repository structure unless explicitly authorized,"
and Rule 40.2 forbids changing locked folder structures without approval.

Taken literally these contradict: honouring Section 4 means restructuring, which
Section 2 and Rule 40.2 forbid.

**Proposed resolution — map, don't move.** Keep `backend/` and add new capability
packages beside the existing ones, mapping Section 4's responsibilities onto
Bob's actual layout:

| Section 4 | Proposed home | Rationale |
|---|---|---|
| `engines/market_data` | `backend/market/` | `san_joaquin.index_ratio` already belongs here |
| `engines/pattern_engine` | `backend/scoring/` | the empty package already exists for this |
| `engines/opportunity_engine` | `backend/scoring/` | co-located with grading |
| `engines/lockout_engine` | `backend/scoring/lockout.py` | shares thresholds with grading |
| `engines/strategy_matrix` | `backend/strategy/` | new |
| `engines/simulation_engine` | `backend/simulation/` | new |
| `engines/negotiation_engine` | `backend/call_planner/` | extends what exists |
| `coordinator/*` | `backend/coordinator/` | new; Bob has no orchestrator |
| `memory/*` | `backend/memory/` | new; `decisions/` folds in |
| `contracts/*` | `backend/contracts/` | **already exists** |

This needs your approval because it declines a literal reading of Section 4.

### D.1b What the follow-up work actually landed

So this document is not read as describing the current tree:

- `backend/scoring/opportunity.py` — Section 22 grading, 57 tests including a
  seeded fuzz of 3,000 hostile inputs.
- `supabase/migrations/20261108_bob_opportunity_overview.sql` — tenant-scoped,
  service-role-only RPC with a covering index, 77 PGlite checks.
- REI-AGENT `db.bob_opportunity_overview` + `GET /api/bob/insights`, and
  `validated_opportunity` carrying the grade into the per-lead snapshot.
- Dashboard `GET /api/v1/bob/insights`, the deals-page panel and the per-lead
  screening block.

A field-name contract is asserted on both sides, so renaming a field in Bob fails
a test naming the consumer rather than silently emptying a column.

### D.2 Boundaries to hold

Section 40's rules 5, 6 and 7 are the ones at real risk as Bob grows:

- Market data must not import negotiation logic, and vice versa.
- Every financial output must come from `finance.py`-style deterministic code. No
  LLM arithmetic. Bob is currently clean here and must stay clean.
- Sophia proposes nothing financial. `call_brief` already carries only an approved
  ceiling, never an authority to offer.

### D.3 Cross-repo conflict: the MAO constant

REI-AGENT's `AGENTS.md` fixes `MAO = (ARV * 0.70) - 2500000`. Section 13 says the
70% rule "must not automatically become the final offer," and Bob already complies
via `flip_analysis`. The two repos therefore disagree.

The fixed $25,000 conflates repairs with assignment fee, so at ARV $200k the offer
is $115,000 whether the house needs $15k or $80k of work. Practitioner sources put
low-ARV deals nearer 60–65% of ARV. **This is your decision, not an engineering
one** — flagged, not changed.

---

## PART E — Mathematical Verification Plan

### E.1 Section 12 coverage, by category

| Category | Items | Present | Coverage |
|---|---|---|---|
| Residential investment | 17 | ~11 | partial |
| Rental investment | 15 | ~9 | partial |
| Commercial investment | 14 | **0** | absent |
| Financing | 18 | ~3 | minimal |
| Creative financing | 12 | **0** | absent |
| Development | 12 | **0** | absent |
| Partnership | 8 | **0** | absent |
| **Total** | **~96** | **~23** | **~24%** |

Present: `repairs_with_contingency`, `screening_mao`, `flip_analysis` (buying/
selling/total cost/profit/ratio/purchase limit), `rental_analysis` (EGI, NOI, cash
flow, DSCR, cap rate, income indication), `mortgage_payment` (P&I, housing cost),
`cost_approach`, `cash_on_cash_return`, plus ARV/as-is/price-per-sqft in the engine.

Absent in full: DCF, NPV, IRR, MIRR, equity multiple, terminal value, reversion
cap, lease rollover, TI/LC, yield on cost, debt yield, LTV, LTC, interest-only,
balloon, points, construction draws, interest reserves, refi proceeds, prepayment
penalties, every creative-financing structure, every development formula, every
partnership waterfall.

### E.2 Correctness audit of what exists

Three findings, none fatal:

1. **`flip_analysis` purchase-limit solve is right.** It divides by `(1 + buy_rate)`
   to handle purchase-dependent buy-side costs, then integer-searches both
   directions to absorb rounding. This is the Section 13 requirement done properly.
   **Limitation, self-documented:** holding and financing are *fixed inputs*, so
   the solve is not exact when financing scales with loan amount. Closing that
   needs a root-find over a cost function of purchase price and term.
2. **`rental_analysis` returns `cap_rate` as NOI ÷ value**, correct, but
   `income_indication_cents` is computed only when `noi > 0`. Negative-NOI cases
   return `None` rather than a negative indication — correct. Section 36 requires a
   negative-NOI test and one exists, verified at `tests/test_valuation.py:328`:
   `noi_cents == -10000 and income_indication_cents is None`.
3. **`cost_approach` raises when depreciation exceeds improvements.** Fails closed,
   correct.

### E.3 Required test contract per Section 12

Each new formula needs, before it ships: explicit definition, inputs with units,
stated assumptions, rounding rule, edge cases, an **independent reference oracle**
(exact `Decimal`/`Fraction`, as `test_valuation_stress` already does), determinism,
and a version tag. Missing inputs must raise, never default to zero — Rule 40.10.

### E.4 Validation datasets needed

| Dataset | Purpose | Status |
|---|---|---|
| San Joaquin closed sales w/ condition | ARV accuracy, ratio study, conformal calibration | **BLOCKED — not licensed** |
| Completed-renovation outcomes | ARV validation per §5.3 | **BLOCKED** |
| Rehab bids vs actual cost | §11 calibration | **BLOCKED** |
| Ames Housing | arithmetic regression only | host unreachable here |
| Synthetic exact oracles | formula correctness | **AVAILABLE — in use** |

---

## PART F — Implementation Roadmap

Mapped onto Section 39's gates, with what is already done struck through.

| Gate | Scope | Files | Acceptance | Blocker |
|---|---|---|---|---|
| **1. Data integrity** | property identity, APN, ownership, source provenance, freshness, dedup | new `backend/identity/`, `backend/providers/` | every fact carries source + retrieval time + effective date + confidence; dedup proven on known-duplicate set | **licensed data** |
| **2. ARV correctness** | ~~comparability gates~~, ~~ratio study~~, ~~drift gate~~, conformal intervals, submarket | `engine.py`, `market_research.py`, new `backend/market/` | COD ≤15, PRD 0.98–1.03, interval coverage ≥85% | calibration set |
| **3. Financial math** | the ~73 absent formulas | `finance.py` + new modules | exact oracle per formula; no LLM arithmetic | none |
| **4. Rehab & feasibility** | 27 line items, local bands, title/zoning/insurance | new `backend/rehab/`, `backend/feasibility/` | bands labelled as assumptions; calibrated vs bids | bid data |
| **5. Deal radar** | continuous discovery, screening, prioritisation | `backend/scoring/` (empty today) | signal stacking measurable; latency budget met | data |
| **6. Buyer demand** | buyer profiles, exit liquidity | new `backend/demand/` | verified vs historical vs unverified buyer separated | data |
| **7. Strategy & simulation** | 14 strategies, stress tests, Monte Carlo | new `backend/strategy/`, `backend/simulation/` | no fabricated probabilities presented as validated | none |
| **8. Orchestration** | coordinator, arbitrator, Karpathys events, approval gates | new `backend/coordinator/` | resumable after interruption; approvals enforced | none |
| **9. Memory & evaluation** | knowledge graph, versioned memory, backtesting, outcome learning | new `backend/memory/` | no silent overwrite; point-in-time, no leakage | outcomes |
| **10. Production reliability** | tracing, circuit breakers, idempotency, cost/latency monitoring | cross-cutting | measured latency, not asserted | none |

### F.1 Expected blockers, ranked

1. **Licensed sold-sale data with condition evidence.** Gates 1, 2, 4, 5, 6 and 9
   all depend on it. This is the program's critical path, and it is a procurement
   and legal decision, not an engineering one. Scrapers are not a substitute:
   HomeHarvest's own README reports Zillow blocking aggressively, a second project
   reports Redfin blocking cloud IPs, and REI-AGENT's `tax_scraper` took a 403 from
   the county in CI this week.
2. **Verified outcomes.** Gate 9 and Section 30 cannot start without closed deals.
3. **Calibration set.** Blocks conformal intervals specifically.
4. **Section 4 restructuring approval.** Blocks Gate 8 cleanly.
5. **Owner decisions.** The MAO constant; scraping posture; TCPA counsel.

### F.2 What is not blocked

Gate 3 (financial mathematics) needs **no external data** — it is pure
deterministic arithmetic with exact oracles, and it is ~76% missing. Gate 7
likewise. If you want visible progress while data procurement runs, those are the
two places to spend effort.

---

## PART G — First Production Gate

**Gate 1, Data Integrity — specifically property identity and sourced comparable
ingestion.**

Why it must come first, in one sentence: **`compare_sales` is a world-class
consumer of evidence that currently has no supplier.**

The engine enforces twelve gates, demands an `evidence_ref` and a `reviewed_by`
on every adjustment, and then labels its own output
`evidence_verification: trusted_input_attestations_not_independent_source_research`.
That string is the honest admission that every gate it enforces is applied to
facts Bob took on trust. Section 6 is entirely absent: no APN resolution, no deed
history, no dedup. So today a caller who supplies three plausible-looking
attestations gets an `ready_advisory` valuation, and the rigour above it is
procedural rather than factual.

Everything downstream inherits that. Gate 2's ratio study measures predictions
against sale prices Bob cannot independently verify. Gate 3's mathematics operates
on an ARV built from unverified comps. Gate 5's radar would rank properties whose
identity is unresolved. Building any of them first means building on attestation.

Concretely, the first unit of work is:

1. A property identity resolver — standardised address plus APN as the canonical
   key, with explicit `verified` / `probable` / `unresolved` / `stale` ownership
   states (Section 6), and a hard rule against merging two parcels on address
   similarity alone.
2. A provider abstraction where every retrieved fact carries source, retrieval
   timestamp, effective date, verification status, confidence and data version
   (Section 26), with licensing recorded per provider.
3. Deduplication proven against a known-duplicate set, since `engine` already
   rejects duplicate `property_id`/`sale_id` but cannot detect the same
   transaction arriving from two providers under different identifiers.

**This is where the program is actually blocked**, and naming that is more useful
than starting Gate 3 because it is unblocked. The engineering for Gate 1 is
straightforward; acquiring the data it ingests is the real decision, and it is
yours: CRMLS (keys are already configured in REI-AGENT), a county Sales Transfer
Journal — Bob's own research notes an official 2021 fee schedule listing one, with
the caveat that a journal alone may not supply concessions, interiors, contract
dates or completed-renovation condition — or a commercial provider.

---

## Awaiting approval

Per Section 42 I have written no code for this specification and will not until you
approve. Three decisions unblock the most:

1. **Section 4 structure** — approve the map-don't-move plan in D.1, or require the
   literal tree.
2. **Data source for Gate 1** — CRMLS, county journal, commercial provider, or
   proceed with attested inputs and accept the ceiling that imposes.
3. **Where to spend effort while data is procured** — Gate 1 engineering against a
   stub provider, or Gate 3 mathematics, which needs nothing external.

Work completed under your prior approval, already pushed: the four comparability
gates, IAAO ratio-study metrics, the output drift gate, Section 22 grading, and the
full Bob-to-dashboard path. 3,539 Bob tests, 77 database checks, ruff clean.
