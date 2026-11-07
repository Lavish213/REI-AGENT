# Open-Source Comparison and Deal-Finding Study

Date: 2026-11-07
Scope: how Bob compares to the best open-source work in the same problem space,
and an end-to-end study of real-estate deal finding with benchmark numbers.

Two sources could not be read from this session: `arxiv.org` and `www.zillow.com`
do not resolve inside this container's network allowlist. Claims attributed to
them below come from search-result summaries, not from the primary documents, and
are marked `[secondary]`. They should be re-read before anything is built on them.

---

## 1. Verdict up front

Bob is not a weaker version of the open-source AVMs. It is a different kind of
system, and the comparison only makes sense once that is stated plainly.

The strongest open-source project in this space — the Cook County Assessor's
`model-res-avm` — is a ~100-feature LightGBM model that **does not use comparable
sales at all**. It values property through neighborhood fixed effects and location
features. Bob is the exact inverse: a comps-only, evidence-adjusted sales-comparison
engine with **no statistical model in the valuation path at all**.

So:

- On **governance, provenance and arithmetic discipline**, Bob is ahead of every
  open-source project surveyed. Not marginally — categorically. Nothing in the
  landscape requires an `evidence_ref` and a `reviewed_by` on every single
  adjustment, refuses to authorize a quote, or labels its own interval as not a
  confidence interval.
- On **statistical calibration**, Bob is behind, and behind in ways that are
  measurable and fixable. It has no accuracy metric any assessor would recognize,
  no drift detection, and an interval whose coverage is capped by arithmetic rather
  than by data.

The useful framing is not "catch up to Cook County." It is: Bob has the audit layer
that the ML projects lack, and lacks the measurement layer they have. Those compose.

---

## 2. What Bob actually is today

Grounded in the code, not the docs.

### 2.1 The valuation path — `backend/valuation/engine.py`

`compare_sales()` is a gated evidence pipeline, not a model. Every comparable must
clear all of:

| Gate | Rule |
|---|---|
| Sale state | `sale_status == 'closed'`, `verified is True`, `arms_length is True` |
| Independence | comp is not the subject; no duplicate `property_id` or `sale_id` |
| Chronology | `contract_on <= closed_on <= available_on <= as_of` |
| Age | `age <= max_age_days`, default **365**, ceiling 730 |
| Distance | `distance <= max_distance_meters`, default **5000**, ceiling 50000 |
| Type | `property_type` must equal the subject's exactly |
| Features | all `FEATURES` keys present, no extras |
| Adjustments | each has `category`, `amount_cents`, `evidence_ref`, `reviewed_by`; no repeated category; concessions cannot be positive |
| Adjustment coverage | `market_time` and `concessions` always required, plus a category for every feature that differs from the subject, plus `location` when `market_area` differs |
| Gross adjustment | `gross <= max_gross_adjustment_bps`, default **3000 bps (30%)** |
| Spread | `max_spread_bps`, default **2000 bps (20%)** |

Rejections are recorded with a reason (`sale_outside_distance_policy`,
`unverified_or_nonclosed_or_nonmarket_sale`, …), so denials are auditable rather
than silent. Arithmetic is exact: `Decimal` and `Fraction`, integer cents, no floats.

Reconciliation (`reconcile_indications`) weights each indication by

```
w = 1 / (1 + age/180 + distance/2000 + |subject_area - comp_area| / subject_area)
```

computed in exact rationals. These three divisors are **hardcoded constants**, not
fitted to anything.

The output is deliberately modest, and this is to Bob's credit:

```
range_meaning:          observed_adjusted_sale_span_not_statistical_confidence_interval
quote_authorized:       False
offer_authorized:       False
evidence_verification:  trusted_input_attestations_not_independent_source_research
```

### 2.2 The model path — `backend/valuation/market_research.py`

Separate from the valuation path. `MarketResearchModel` works in log-price space
(`log_to_cents`) and has `calibration_radius(scores, alpha_bps=1000)` — a split-
conformal quantile at the 90% level. So Bob *does* have conformal machinery. Two
problems: it is a **single global radius** (constant width — see §5.5), and this
module sits at **29.9% test coverage**, the lowest in the repo, so it is effectively
unvalidated.

### 2.3 Local grounding — `backend/valuation/san_joaquin.py`

Genuinely good and not something the open-source projects have: county FIPS `06077`
hardcoded, a real parcel authority (`sjmap.org` ArcGIS REST MapServer), an
`index_ratio(series, from_year, to_year, as_of)` time-index helper, and a
`REVIEW_ITEMS` tuple naming seven concrete local review obligations — levee/flood
evidence, permitted living area and ADU scope, unincorporated permit authority,
supplemental tax assessments, rural utilities and land contracts.

### 2.4 Lead scoring — `REI-AGENT/backend/scout/scorer.py`

Additive rule-based motivation score, capped at 100. Single signals:

| Signal | Points |
|---|---|
| Notice of trustee sale | +65 |
| Pre-foreclosure / NOD | +55 |
| Tax delinquent 3+ yrs | +45 |
| Tax delinquent 1–2 yrs | +30 |
| Vacant | +42 |
| Owner mailing state ≠ CA | +30 |
| Lien > $5,000 | +25 |
| Absentee owner | +22 |
| Code violation | +18 |
| Free and clear | +15 |
| Tenure 20+ yrs | +20 |

Plus explicit **stacking bonuses**: vacant+preFC +28, vacant+absentee +22,
absentee+tax_del +20, tax_del+free_clear +20, preFC+equity≥50% +22, and a breadth
bonus of +25 at 4+ distinct signals / +15 at 3.

This is the part of the system that most closely matches outside best practice.
Every practitioner source surveyed independently converged on the same claim — that
stacked signals beat any single list — and Bob's scorer already encodes it
numerically. Disqualifiers are also sensible: land/commercial/mobile types,
address tokens (`lot`, `acreage`, `parcel`), no beds, sqft < 400, owned < 6 months.

---

## 3. The open-source landscape

| Project | What it is | License | Relevance to Bob |
|---|---|---|---|
| **ccao-data/model-res-avm** | Cook County Assessor production AVM. LightGBM, ~100 features, 9 yrs sales | AGPLv3 (archived GitLab) | **Highest.** The engineering and measurement benchmark |
| **ccao-data/model-condo-avm** | Same team, condo classes | — | Same patterns, condo-specific |
| **Bunsly/HomeHarvest** | Zillow / Realtor / Redfin scraper → MLS-style DataFrame | MIT, ~218★ | Direct overlap with `comps/redfin.py` |
| **Retrieval-Enhanced Real Estate Appraisal** | Learned comparable selection `[secondary]` | paper | **Highest research leverage** |
| **Siamese-network AVM** | Learns comparability + adjustment weighting | **USPTO patent** | Technique reference only — patent risk |
| **McCluskey & Borst (2017)** | Classic comp-selection chapter; Mahalanobis/Manhattan distance, spatial autocorrelation | Springer | Theory for §5.2 |
| **PySAL / `spreg` / `mgwr`** | Spatial econometrics, geographically weighted regression | BSD | Submarket heterogeneity |
| **rlowrance/re-avm** | Small research AVM | BSD-3 | Little |
| **ml-property-valuation-avm** | Ridge/RF/XGBoost benchmark, XGBoost R²=0.835 | MIT | Little — R² is the wrong metric here |
| **BrittanyNation/deal-analyzer** | Wholesale MAO calculator, React | — | MAO formula comparison (§5.6) |
| **Rental-Property-Deal-Analyzer** | 20+ metrics, point scorecard | — | Notes Redfin blocks cloud IPs |
| **johnkmaxi/lead-machine** | Crawler + analyzer + DB for finding deals | — | Closest in *intent*, sparse in fact |
| **ahsaxyz/ai-agent-real-estate** | Agent framework for market scan / deal flagging | MIT | Early-stage |
| **ahacker-1/cre-agent-skills** | 17 CRE underwriting/DD skills as prompts | — | Prompt patterns, commercial |
| **CentralizedAppraiser** | Pulls county appraiser data directly | — | Only 2 FL counties; still needs a Regrid key |

### 3.1 Cook County in detail — the one to actually study

This is a production government AVM with its code open, which makes it the only
honest engineering benchmark in the list.

- **Model:** county-wide LightGBM on 9 years of prior sales. They tested linear
  models, XGBoost, CatBoost, random forests, neural nets, SVMs and stacking, and
  chose LightGBM for accuracy, speed and native categorical handling. Bayesian
  hyperparameter optimization. A custom R package (`Lightsnip`) adds early stopping
  and links `num_leaves`/`max_depth`.
- **Features (~100):** structural characteristics; ACS 5-year census (income, age,
  education, household structure); location (lat/lon, walkability, flood risk,
  school district, tax municipality); proximity (transit, parks, roads, water,
  noise, traffic counts); parcel shape; time of sale; neighborhood/township codes.
- **Documented exclusions** with reasons — property condition, interior finishes,
  crime. Worth noting: they *exclude condition*. Bob's whole ARV problem is condition.
- **Comparables:** not used for valuation. Neighborhood fixed effects instead. An
  experimental comps feature derived from **LightGBM leaf-node co-occurrence** is
  generated during interpretation but unused. That is a cheap, strong idea: two
  properties landing in the same leaves across many trees are model-comparable.
- **Validation:** most recent 10% of sales held out; rolling-origin resampling for
  hyperparameters on time-ordered data; a second random non-time-based test set to
  check generalization; final retrain on all sales.
- **Metrics:** assessor-standard **COD, PRD, PRB, MKI** alongside RMSE/MAE/MAPE/R².
- **Engineering:** 7-stage pipeline, each an R script, orchestrated with **DVC** on
  S3; `renv` lockfiles; published Docker image; GitHub Actions + AWS Batch with
  approval gates; every run's outputs saved as Parquet and queryable in Athena;
  **CI checks that code changes don't cause significant output changes**; sales
  validation in a separate repo; balance-test reports committed.

The last CI point is the single most transferable practice: a test that fails when
model *output* moves unexpectedly, independent of whether the code looks correct.

### 3.2 HomeHarvest — and why it is a trap worth naming

MIT, scrapes Zillow/Realtor/Redfin into MLS-shaped pandas frames, supports
`for_sale` / `for_rent` / `sold` / `pending`. The reason to be careful is in its own
README: heavy use gets you blocked, 403 means you have been blocked, and **Zillow is
particularly aggressive**. Its suggested mitigation is a VPN to change IP. The
Rental-Property-Deal-Analyzer README independently reports that **Redfin blocks
cloud servers** — which is exactly the failure mode Bob's own `tax_scraper` hit in
CI today (403 from the county auction page during a test run).

Two conclusions. First, scraping is not a durable comp supply for a system that is
supposed to run unattended on Railway. Second, the ToS exposure is real and none of
these projects addresses it. Licensed data (CRMLS, which Bob already has keys
configured for) is the load-bearing path; scrapers are a supplement.

### 3.3 Learned comp selection — the highest-leverage idea found

`[secondary — arxiv.org unreachable from this session]` The Retrieval-Enhanced Real
Estate Appraisal preprint argues that while valuation models have grown
sophisticated in price regression, **their comparable-selection policy remains
relatively naive**. It frames selection as retrieval-enhanced ML, learns the
selector, and reports needing **fewer comparables to reach comparable accuracy**.

That critique describes Bob's engine precisely. Bob's selection is a hard threshold
on distance and age, followed by fixed hand-chosen weights with divisors of 180,
2000 and 1.0. There is no learning anywhere in the selection path.

---

## 4. Where Bob is genuinely ahead

Stated carefully, because it matters for deciding what *not* to rewrite.

1. **Per-adjustment provenance.** Every adjustment carries `evidence_ref` and
   `reviewed_by`. No surveyed open-source project has this. It is what separates a
   defensible valuation from a number.
2. **Mandatory adjustment coverage.** Bob computes which categories are *required*
   from the subject/comp feature diff and rejects the comp if any are missing. The
   OSS deal analyzers accept whatever you type in.
3. **Exact arithmetic.** `Decimal`/`Fraction`, integer cents throughout. The
   React/Python deal analyzers use floats for money.
4. **Refusal as a first-class output.** `quote_authorized: False`,
   `offer_authorized: False`, and rejection records with reasons. The system can
   decline and explain.
5. **Honest interval labeling.** `observed_adjusted_sale_span_not_statistical_confidence_interval`
   is more truthful than most *commercial* AVMs, which present a range and imply
   confidence. Zillow's own figure is a *median* error, meaning half of estimates
   fall outside the stated margin — a nuance its UI does not stress.
6. **Local obligation encoding.** The seven `REVIEW_ITEMS` for San Joaquin
   (levee/flood, ADU scope, permit authority, supplemental assessments, rural
   utilities) are real local underwriting risks. Generic projects have no equivalent.
7. **Test and authorization discipline.** 3,455 tests passing, 457 mutations with
   **0 authorization violations**. Nothing in the OSS landscape is tested to this level.

---

## 5. Where Bob is behind, in priority order

### 5.1 No per-line adjustment cap (correctness, cheap fix)

An appraisal QC patent describes flagging **any single line-item adjustment above
10% of the comp's sale price**. Bob caps *gross* adjustment at 3000 bps but has no
per-category cap. A single 29% location adjustment passes today, and gross-only
capping is exactly the hole that lets one heroic adjustment carry a bad comp.

Fix: add `max_line_adjustment_bps` (start 1000) and reject with
`single_adjustment_exceeds_line_policy`.

### 5.2 Comp selection is the "naive policy" the literature names

- `max_distance_meters` default **5000** is far too wide for Stockton. 5 km crosses
  between non-competing submarkets — Miracle Mile, Brookside and south Stockton are
  all inside one 5 km radius and do not trade alike. Freddie Mac's guide leans on
  proximity; the earlier internal recommendation of **800 m** is better supported.
- `max_age_days` **365** matches Freddie Mac's 12-month expectation, so it is
  defensible — but in a moving market **180** with an explicit index adjustment is
  tighter.
- No **area-divergence gate** at all. A 1,200 sqft comp for a 2,400 sqft subject
  clears distance and age and is merely *adjusted*. Appraisal practice bounds
  comparability itself: good selection keeps adjustments both fewer and smaller.

Fix: `max_area_divergence_bps` (±1000), tighten distance to 800 m, age to 180 d.
These are policy-dict changes, already plumbed.

### 5.3 ARV is computed from non-renovated comps (the biggest economic error)

ARV means *after repair* value. Deriving it from ordinary closed sales — most of
which are not renovated — biases it low, and because MAO is a fraction of ARV, the
error propagates straight into every offer. The practitioner literature's phrasing
is blunt: cost is not value, and an optimistic ARV "inflates the offer twice."

Bob's engine has no notion of comp condition, and Cook County **explicitly excludes
condition** from its feature set — so there is no open-source precedent to copy here.
This has to be built.

Fix: for `purpose == 'after_repair'`, require comps carrying a renovated-condition
attestation, and reject with `after_repair_requires_renovated_comp_evidence`.

### 5.4 No accuracy metric an assessor would accept

Bob reports no COD, PRD, PRB or MKI. Industry targets:

| Metric | Acceptable | Notes |
|---|---|---|
| COD | ≤ 15% residential | 5–10 newer/homogeneous, 5–15 older/heterogeneous |
| PRD | 0.98 – 1.03 | >1.03 regressive, <0.98 progressive |
| Median ratio | 0.95 – 1.05 | some jurisdictions use 0.90–1.10 |

Until these exist there is no answer to "is Bob getting better or worse." Cook
County computes all four every run and gates CI on output drift.

### 5.5 The interval is structurally incapable of 90% coverage

Two separate problems:

**(a) The observed-span interval.** Using the min/max of the accepted adjusted
indications caps coverage at `(n-1)/(n+1)` for exchangeable draws — confirmed to
within 0.1% over 1.8M trials in earlier work. At 3 comps that is **50%**; at 5,
**66.7%**. No amount of better comps fixes this; it is arithmetic.

**(b) The conformal radius is constant-width.** `calibration_radius(scores,
alpha_bps=1000)` returns one global radius. The conformal literature flags this
exact failure: a single half-width means cheap homes get ranges wider than the house
is worth while expensive homes get ranges that are too tight, and false coverage
becomes inflated for high-priced homes. The fix is a **locally-weighted or
normalized nonconformity score** so width tracks difficulty.

Fix: replace the span with locally-normalized split-conformal intervals, keep the
span as a *reported diagnostic* rather than the interval. Requires a San Joaquin
calibration set — still the blocking dependency.

### 5.6 The MAO formula breaks at the low end of the local market

Bob: `MAO = (ARV * 0.70) - 2,500,000 cents`, i.e. ARV×0.70 − $25,000, with repairs
and fee folded into one constant. Compare the OSS wholesale analyzer:
`MAO = ARV × 0.70 − repairs − $10,000`, which at least keeps repairs variable.

The practitioner critique is specific and applies directly to San Joaquin, where
plenty of stock trades under $300k: the 30% margin is a *fixed share*, so in
low-ARV markets — where fixed costs eat a small spread — offers need to be nearer
**60–65%** of ARV. One source puts it concretely: a $600k ARV at 75% leaves $150k
before repairs, while a $200k ARV at 70% leaves only $60k.

At ARV $200k Bob offers `140,000 − 25,000 = $115,000` regardless of whether the
house needs $15k or $80k of work. That is not a screen, it is a coin flip.

Note this is constrained: `AGENTS.md` fixes the formula as
`(ARV * 0.70) - 2500000`. Changing it is an owner decision, not an engineering one.
Flagging it, not proposing to unilaterally change it.

### 5.7 No market-time index actually applied

`san_joaquin.py` has `index_ratio()`, and the engine *requires* a `market_time`
adjustment on every comp — but as an attested input someone else supplies, not as
something Bob computes. The standard approach is a hedonic model plus a repeat-sales
index (FHFA `ATNHPIUS06077A` is the San Joaquin series). Wiring `index_ratio` into
an auto-derived `market_time` adjustment with the index as its `evidence_ref` would
close a real gap and *strengthen* the evidence chain rather than weaken it.

### 5.8 No submarket segmentation

`market_area` is compared as an opaque token — equal or not. The spatial-econometrics
literature treats this as the core problem: global hedonic models that ignore spatial
dependency and heterogeneity are superseded by GWR and spatial lag/error models,
which fit a separate local relationship per location. `mgwr` and `spreg` (PySAL, BSD)
are the ready tools; a London study used GWR over 19 years to show determinants vary
across both space and time.

---

## 6. Deal finding end to end, with benchmarks

All vendor-sourced numbers below are directional. Practitioner blogs and list
sellers have an obvious incentive in these figures and none of them publish method.
The IAAO, Freddie Mac, HUD and Cook County figures are the reliable ones.

### Stage 1 — Data sourcing

| Source | Reality |
|---|---|
| County records (tax, NOD, lis pendens, probate) | The real substrate. Free, authoritative, per-county formats. Bob scrapes San Joaquin TTC directly |
| List brokers | ~$0.05–0.30/record; a snapshot, stale on arrival |
| Aggregators (PropStream etc.) | Filterable stacked signals; what Bob is replacing |
| **Regrid / Landgrid** | Free parcel **boundary tiles** only; attributes paid; API trial **restricted to 7 counties** |
| **HUD USPS vacancy** | Quarterly, 90+ day vacancy. **Census-tract aggregated only** — unusable for parcel targeting. `No-Stat` category is partly vacant too; a 2010 procedure change and post-2011 address-count growth make naive rate math wrong |
| MLS (CRMLS) | The licensed, durable path. Bob has keys configured |
| Scrapers | 403s, cloud-IP blocks, ToS exposure |

The HUD finding is worth internalizing: the most-cited "free vacancy data" cannot
drive individual outreach. Vacancy has to come from field or county signals.

### Stage 2 — Signal stacking and scoring

Every source converged: stacking beats any single list. Tax lien + high equity means
an owner with value to extract *and* a reason to act; pre-foreclosure + absentee
means an out-of-state owner unlikely to fight for a house they have not lived in.
The highest-value signals are the ones with an **externally imposed deadline the
owner cannot postpone** — pre-foreclosure, probate, tax delinquency.

Bob's scorer already implements this, including breadth bonuses. This is its
strongest component. Caveat from a practitioner forum: the obvious lists are
getting more competition, and public county tax lists get mailed by everyone.

### Stage 3 — Skip trace and contact

Bob has `contacts` and a `BATCHDATA_API_KEY`. Nothing in the open-source landscape
addresses this stage at all.

### Stage 4 — Outreach

| Channel | Response | → deal | Cost/deal |
|---|---|---|---|
| Direct mail | 0.5–2% typical; 2–5% fresh probate/pre-FC; 3–7% claimed for yellow letters | 5–10% of responses | $1,500–5,000 (one source $500–2,000) |
| Cold call | 12–18% contact rate of dials; 8–15% of contacts convert | 800–1,200 dials | $200–1,000 cash; $2,000–7,000 with time |
| Multi-channel | one anecdote: mail+call+SMS roughly doubled deals from the same list | — | — |

ANA/DMA cross-industry averages: 4.4% house lists, 2.7% prospect lists. One survey
reports **~$2,300 per signed contract** nationally over 12 months. The consistent
message across sources is that cost per deal matters more than response rate, and
list quality moves results far more than creative does.

This stage is where Sophia lives, and where the TCPA/SB 1001 constraints bind
hardest. Those are legal limits on *volume*, which is precisely the lever these
benchmarks assume you can pull. Bob's edge has to come from list quality and
valuation accuracy, not dial count.

### Stage 5 — Valuation

| Benchmark | Value |
|---|---|
| Zillow on-market median error | ~1.83% `[secondary]` |
| Zillow **off-market** median error | **~7.01%** (Jul 2025) `[secondary]` |
| Zillow off-market by state | ~4.5% Nevada to ~12.7% Vermont `[secondary]` |
| Zillow Prize winner | beat Zestimate ~13%, pushed error below 4% |
| Bob's measured error | **9.86%** |
| IAAO COD | ≤15% residential |
| IAAO PRD | 0.98–1.03 |
| Freddie Mac comps | ≥3, closed within 12 months |
| RSMeans sqft models | vendor calls them "conceptual / ballpark"; third-party cites ±15–25% parametric |

Off-market is the right comparison for Bob, since distressed sellers are by
definition not on-market. Against ~7% off-market, Bob's **9.86% is respectable** —
a few points behind a company with a national data moat, and the earlier "<7%
stretch target" turns out to be roughly *Zillow's own off-market accuracy*, which
is a far more demanding goal than it sounds.

The repair side is weaker than the valuation side and gets less attention: RSMeans'
own guidance calls square-foot figures ballpark, and renovation is harder to price
per square foot than new build. A ±20% repair estimate on a $60k rehab is ±$12k
straight off the margin.

### Stage 6 — Underwriting and offer

The 70% rule is a **screen, not a model** — every source says so, and §5.6 covers
how it fails at low ARV.

### Stage 7 — Disposition

`cash_buyers` and `deal_blast_sends` exist in Bob's schema; `buyer_discovery` was
wired to a weekly job today. No open-source project surveyed covers disposition.

---

## 7. What to do, in order

Ordered by (value × confidence) ÷ cost. Items 1–4 are policy and gating changes
inside the existing architecture — no new dependencies, no new data.

| # | Change | Why | Cost |
|---|---|---|---|
| 1 | `max_line_adjustment_bps` = 1000 | Industry QC flags any line >10% of comp price; gross-only capping lets one heroic adjustment carry a bad comp | hours |
| 2 | `max_area_divergence_bps` = ±1000 | No size-comparability bound exists today | hours |
| 3 | distance 5000 → **800 m**, age 365 → **180 d** | 5 km spans non-competing Stockton submarkets | hours |
| 4 | Renovated-comp requirement for `after_repair` | Largest economic error in the system; ARV bias flows into every MAO | 1–2 days |
| 5 | COD / PRD / PRB on a holdout + CI drift gate | Cook County's practice; without it "better" is unmeasurable | 2–3 days |
| 6 | Auto-derive `market_time` from `index_ratio` + FHFA `ATNHPIUS06077A` | Closes a gap *and* strengthens the evidence chain | 2–3 days |
| 7 | Locally-normalized conformal intervals; demote span to diagnostic | Current interval caps at 50% coverage at 3 comps | blocked on calibration set |
| 8 | Raise `market_research.py` above 29.9% coverage | The only conformal machinery in the system is unvalidated | 1–2 days |
| 9 | LightGBM leaf-node co-occurrence as a comp-similarity signal | Cook County built it and left it unused — cheap to test, no new data | spike |
| 10 | GWR / spatial lag via `mgwr`, `spreg` | Replace opaque `market_area` token equality with real submarket structure | 1 week |
| 11 | Learned comp selection (retrieval-enhanced) | Highest research ceiling; directly answers the "naive policy" critique | research |

Owner decisions, not engineering ones:

- **The MAO constant.** `AGENTS.md` fixes `(ARV * 0.70) - 2500000`. The fixed $25k
  conflates repairs with fee and misprices low-ARV deals. Recommend ARV-banded
  percentage with repairs as a separate variable term — but that is Angelo's call.
- **Scraping posture.** Licensed CRMLS vs. scrapers that 403 from cloud IPs and
  carry ToS exposure. The open-source landscape has no answer here; it just scrapes.
- **Items 1–4 touch Bob**, which the standing directive placed under read-only.
  They need that lifted before implementation.

---

## 8. The one-line summary

Bob's audit layer is better than the open-source field's and its measurement layer
is worse; the field's best project (Cook County) proves you can have rigorous
measurement without comps at all, and the research frontier says the comp-selection
policy Bob relies on is the naive part of every system that has one. Fix the four
cheap gates, then start measuring in COD and PRD, and the "is it improving?"
question becomes answerable for the first time.

---

## 9. Sources

Open-source projects
- https://github.com/ccao-data/model-res-avm
- https://github.com/ccao-data/model-condo-avm
- https://gitlab.com/ccao-data-science---modeling/models/ccao_res_avm
- https://github.com/Bunsly/HomeHarvest
- https://pypi.org/project/homeharvest/
- https://github.com/rlowrance/re-avm
- https://github.com/navanshi-parekh/ml-property-valuation-avm
- https://github.com/Linhkust/ML-based-AVM
- https://github.com/axiom-stat/econometric-market-valuation
- https://github.com/BayleeD2/Zillow_AVM
- https://github.com/BrittanyNation/deal-analyzer
- https://github.com/berkcankapusuzoglu/Rental-Property-Deal-Analyzer
- https://github.com/johnkmaxi/lead-machine
- https://github.com/Deal-Scale/awesome-real-estate-investing
- https://github.com/ahsaxyz/ai-agent-real-estate
- https://github.com/Ishita1406/PropertyAI
- https://github.com/ahacker-1/cre-agent-skills
- https://github.com/ReedGraff/CentralizedAppraiser
- https://github.com/AubinEspinas/california-housing-conformal-prediction

Valuation method and standards
- https://guide.freddiemac.com/app/guide/section/5605.6
- https://en.wikipedia.org/wiki/Sales_comparison_approach
- https://en.wikipedia.org/wiki/Automated_valuation_model
- https://www.mckissock.com/blog/appraisal/the-sales-comparison-approach-a-cornerstone-of-real-estate-appraisal/
- https://www.extension.iastate.edu/agdm/articles/chandio/ChaApr26.html
- https://link.springer.com/chapter/10.1007/978-3-319-49746-4_17
- https://www.progress.org/wiki/iaao-standards/
- https://www.phila.gov/media/20240920162058/opa-tax-year-2025-residential-ratio-study.pdf
- https://prodassets.cookcountyassessoril.gov/s3fs-public/reports/2019_IAAO_sales_ratio_study_final.pdf
- https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8244563
- https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11481818
- https://www.nature.com/articles/s41598-025-34099-9
- https://doi.org/10.3390/realestate2030012

Spatial and uncertainty methods
- https://sustainability-gis.readthedocs.io/en/latest/tutorials/spatial_regression.html
- https://link.springer.com/chapter/10.1007/978-981-96-5589-2_6
- https://towardsdatascience.com/use-case-adapted-prediction-intervals-by-means-of-conformal-predictions-and-a-custom-non-conformity-b4fb28d2a4f7/

Market accuracy
- https://www.zillow.com/zestimate (not readable from this session)
- https://www.zillow.com/tech/zillow-prize-big-reveal (not readable from this session)
- https://venturebeat.com/ai/zillow-awards-1-million-to-team-that-reduced-home-valuation-algorithm-error-to-below-4
- https://listwithclever.com/real-estate-blog/how-accurate-is-a-zillow-zestimate-5-things-to-know/
- https://www.realestatewitch.com/most-accurate-home-value-websites/

Data sources
- https://www.huduser.gov/portal/datasets/usps.html
- https://www.HUDUser.gov/portal/sites/default/files/pdf/2018-USPS-FAQ.pdf
- https://regrid.com/api
- https://support.regrid.com/api/parcel-api-endpoints
- https://www.rsmeans.com/resources/square-foot-estimating

Practitioner benchmarks (vendor-sourced, directional)
- https://www.propstream.com/real-estate-investor-blog/how-to-find-distressed-properties
- https://ispeedtolead.com/blog/distressed-property-lead-sources/
- https://ispeedtolead.com/blog/how-much-do-motivated-seller-leads-cost-in-2026/
- https://www.propertyreach.com/blog/motivated-seller-leads-complete-guide-for-investors-2026/
- https://televistaleadgeneration.com/blog/2026/06/13/2026-real-estate-cost-per-deal-benchmarks/
- https://www.remaildirect.com/blog/direct-mail-response-rates
- https://yellowletter.com/how-to-measure-response-rate-from-direct-mail/
- https://www.biggerpockets.com/forums/311/topics/1295961-distressed-property-leads-drying-up-or-just-harder-to-spot
- https://www.realestateskills.com/blog/what-is-70-rule-in-house-flipping
- https://www.propstream.com/news/what-is-the-70-rule-for-fix-and-flippers
- https://usetruecap.com/blog/70-percent-rule-house-flipping
