# Valuation & Deal-Finding — What the Field Knows

**Date:** 2026-11-07 · Research pass, no code changes.

This is not another audit. It is what I could learn from open sources about how
ARV estimation and off-market deal finding are actually done well, and what it
says about Bob.

**Source quality caveat up front:** most accuracy figures below come from
vendor pages and investor blogs, not primary methodology disclosures. The
conformal-prediction material is peer-reviewed and is the most reliable part of
this document. Where sources conflict I say so.

---

## 1. The benchmark we were missing

Bob's held-out result is **9.86% MdAPE**. Until now I had nothing to compare it
to, so I could not say whether that was good. Here is the reference:

| Estimator | On-market median error | Off-market median error |
|---|---|---|
| Zillow Zestimate | ~1.7–2.4% | **~6.9–7.0%** |
| Redfin Estimate | ~1.9–2.1% | **~5.8–7.4%** |
| HouseCanary (self-reported) | ~2.2–2.8% | not published |
| **Bob** (Ames 2010 held-out, as-is) | — | **9.86%** |

Sources disagree on the ordering of Zillow vs Redfin and the figures are
secondhand, but they cluster tightly enough to be useful: **on-market ≈ 2%,
off-market ≈ 6–8%.**

### Three conclusions that change how we should read Bob

**1. 9.86% is respectable, not bad.** It is a few points behind Zillow and
Redfin *on the off-market case*, achieved by a solo-built engine on a 1,943-row
1920s–2010 Iowa dataset, against companies with national transaction coverage
and a decade of investment. I had been treating that number as a weak result.
It is not.

**2. Off-market is the hard case, and it is our only case.** Wholesaling targets
properties that are not listed. The ~2% on-market figure is irrelevant to this
business. The relevant bar is ~7%.

**3. Part 22's "stretch target below 7%" is approximately Zillow's off-market
accuracy.** That is worth knowing before anyone treats missing it as failure.
It is a state-of-the-art-with-national-data target. The "initial below 10%"
target, which Bob already meets, is the realistic one.

And a caveat in the other direction: Bob's figure is **as-is sale price**, not
ARV. ARV is strictly harder — you are predicting the price of a house in a
condition it is not currently in. Expect ARV error to exceed as-is error.

---

## 2. The standard AVM architecture — and Bob already has both halves

Wikipedia's [AVM entry](https://en.wikipedia.org/wiki/Automated_valuation_model)
states that most AVMs combine **a hedonic model with a repeat-transaction
index**. That is the canonical two-part design.

Bob has both, which I had not credited:

| Component | Bob's implementation |
|---|---|
| Hedonic model | `valuation/market_research.py` — log-space regression with calibration radii |
| Repeat-sales index | `valuation/san_joaquin.py` — pins FHFA series **`ATNHPIUS06077A`**, the San Joaquin County annual HPI, which *is* repeat-sales based |

So the architecture is right. The problem is weighting: `market_research.py` is
the module measured at **29.9% test coverage** (experiment E-7) and the only one
using `float`. The hedonic half is the least-tested code in the repository.

---

## 3. ARV is not market value, and that is the core gap

This is the most important thing I learned, and it sharpens finding B-4 well
beyond "the label is the only difference."

**The naive formula is wrong.** [REIkit](https://www.reikit.com/house-flipping-guide/arv-real-estate-meaning-calculate-after-repair-value)
argues directly that `purchase price + renovation cost = ARV` is invalid,
because **cost is not value**. $60k of renovation does not add $60k of value;
it adds whatever the market pays for that renovation, which can be more or
less.

**The appraisal-style method** is: value the unrepaired property, then add the
**market value of the repairs** — not their cost.

**ARV requires sold, renovated comparables.** Not any sold comp. Comps that
closed in post-renovation condition. This is the structural requirement Bob's
engine cannot currently express: `compare_sales` accepts
`purpose='after_repair'` and a `renovation_plan_ref` token it never
dereferences, and it has **no way to require that accepted comps are
renovated-condition sales**. It validates `condition` and `quality` as opaque
tokens.

So B-4 is not "a missing feature." It is that **ARV needs a different comp
population**, and the engine has no filter for it.

---

## 4. Industry comp rules are tighter than Bob's defaults

Practitioner guidance, consistently across sources
([REIkit](https://www.reikit.com/house-flipping-guide/arv-real-estate-meaning-calculate-after-repair-value),
[Real Estate Skills](https://www.realestateskills.com/blog/arv-calculator),
[Hard Money Co](https://thehardmoneyco.com/wp-content/uploads/2022/08/UARV_Presentation_10.7.20.pdf)):

| Rule | Industry practice | Bob's current policy |
|---|---|---|
| Distance | ≤ 0.5 mi | `max_distance_meters` default **5,000 m (3.1 mi)** |
| Recency | 90–180 days | `max_age_days` default **365** |
| Square footage | within ±10% | **no ceiling at all** — finding B-3 |
| Bed / bath | match | required *adjustment*, no divergence limit |
| Age | within 5–10 years | not a policy field |
| Sold only | never active or pending | ✅ Bob enforces `sale_status == 'closed'` |

**Finding B-3 is now confirmed as a real deviation from practice, not a
theoretical one.** My experiment showed a comp **+3233% larger** than the
subject still returns `ready_advisory`. Industry practice would reject anything
beyond ±10%.

Bob's defaults are 6× looser on distance and 2–4× looser on recency than
practitioner guidance. The counter-argument is real — a thin Stockton submarket
may not yield three comps inside 0.5 mi / 90 days — but then the honest response
is to *widen and say so*, which Bob is already built to do via `review_reasons`.
It does not currently say so, because no policy field tracks it.

What Bob does better than the guidance: it requires explicit per-category
adjustments with `evidence_ref` and `reviewed_by`, and it refuses to quote at
all when dispersion is wide. Most calculators just average.

---

## 5. Conformal prediction — the rigorous fix for the interval problem

My experiments E-5 and E-11 established that Bob's interval coverage is capped
at `(n−1)/(n+1)` by comp count — 50% at three comps, 66.7% at five — and that
scaling the span to reach 80% costs an uninformative width. I concluded the comp
span is the wrong object to calibrate. The literature agrees and names the
replacement.

**Conformal prediction** produces intervals with *theoretically guaranteed*
coverage, applied as a calibration layer on top of an existing model
([arXiv:2312.06531](https://arxiv.org/html/2312.06531v1),
[Springer, J. Real Estate Finance & Economics](https://link.springer.com/article/10.1007/s11146-024-10002-7)).
It does not require replacing the valuation engine — it wraps it.

### The literature documents the exact failure mode I measured

From the locally-weighted CP paper: *"direct application of CP leads to
confidence sets that are not calibrated everywhere, i.e., too large of
confidence sets in certain geographical regions and too small in others."*

And a [California housing demo](https://github.com/AubinEspinas/california-housing-conformal-prediction)
reports ~90% average coverage at a 10% significance level, but **80–87% at the
cheapest and most expensive price bands** versus >90% mid-range.

That is Bob's worst case exactly. The benchmark artifact's most extreme error
is a property that **sold for $62,383 against a $127,178 estimate** — a cheap
house, in the band where coverage is documented to degrade.

### The two refinements that matter here

1. **Locally weighted nonconformity scores** — calibrate against nearby
   properties rather than globally. Fixes the geographic unevenness.
2. **Normalized nonconformity measures** — scale the score by predicted
   difficulty, producing *narrower* intervals where evidence is strong and wider
   where it is thin ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0957417421006059)).

The second one directly answers my B-10 objection. I rejected span-scaling
because 80% coverage required ~85% width uniformly. Normalized conformal gives
a *tight* interval on a clean five-comp set and a wide one on a dispersed set —
which is what an underwriter actually needs.

### Honest note on feasibility

Conformal prediction needs a **calibration set**: held-out sales with known
outcomes in the operating market. Bob does not have San Joaquin sales with
verified outcomes. So this is the right technique and it is **not available
today** — it is blocked on the same data gap as everything else. Pretending
otherwise would repeat the mistake of quoting the Iowa figure as if it were a
California one.

---

## 6. Techniques worth borrowing

| Technique | Where seen | Relevance |
|---|---|---|
| **Out-of-fold spatial price features** | [property-avm-xgboost](https://github.com/ainifadillahn/property-avm-xgboost) | Neighborhood price features computed out-of-fold to prevent target leakage. Bob's leakage discipline is already strong; this is the technique for adding spatial features without breaking it |
| **SHAP attribution** | same | Per-prediction explanation. Bob returns `accepted_comparables` with weights, which is arguably better — comp-level attribution is more defensible to a seller than a SHAP value |
| **Cross-validated prediction intervals** | [hedonic-property-valuation](https://github.com/PeterJemley/hedonic-property-valuation) | Reports CV accuracy *and* intervals together |
| **Hedonic + GBM comparison on one dataset** | [riyadh-housing-valuation](https://github.com/yasirAlot/riyadh-housing-valuation) | The benchmark design Bob already follows — simple baseline vs model, same subjects |
| **Coverage gap as a first-class metric** | CP literature | Report target minus empirical coverage, **per segment**, not just marginally. Bob reports `observed_comp_span_contains_sale` as a count; it should be a gap, stratified |

Bob is not behind on method discipline. Its exact-oracle `Fraction` tests and
frozen held-out split are better than most of these repositories. It is behind
on **uncertainty quantification** and **market-local data**.

---

## 7. Deal finding — what the data landscape says

Measured state of our funnel (same session): 9 scrapers exist, **3 can produce
leads today** without additional setup. 3 are orphaned, including
`tax_scraper`, whose signal the scorer weights at **+45**.

What the vendor landscape says
([Olostep](https://www.olostep.com/blog/best-real-estate-data-providers),
[ProbateData](https://www.probatedata.com/blog/best-property-data-tools-for-off-market-real-estate-prospecting-2026),
[Jamil Academy](https://www.jamilacademy.com/blog/propstream-vs-batchleads-vs-dealmachine)):

- **BatchData is the API-first option** — ~150M properties, 600+ data points,
  real-time. **We already have `backend/lib/batchdata.py` (404 lines) and
  `BATCHDATA_API_KEY`.** That is the correct architectural choice already made.
- **PropStream is self-serve, not an API** — built for individual investors, not
  engineering integration. Good for manual comp pulls, wrong for a pipeline.
- **Probate data is stale in general-purpose tools** — filings often weeks
  behind, specialist sources recommended. Relevant because `court_scraper`
  (probate/divorce/judgments, 213 lines) is orphaned anyway.
- One source claims PropStream acquired BatchLeads and BatchDialer in July 2025.
  **Unverified single claim** — check directly before it matters commercially.

**The strategic read:** we are not short of *sources*, we are short of *wiring*.
Three orphaned scrapers and three unconfigured ones is a plumbing problem, not
a data-acquisition problem. BatchData already covers motivation filters
(vacant, absentee, pre-foreclosure, tax delinquent) through an API we have code
for.

---

## 8. What I would change, in order

1. **Wire `tax_scraper` into `run_scout_cycle`.** One line. Unlocks the
   third-heaviest distress signal, which is currently scraped by code nothing
   calls.
2. **Add the six missing env vars to `.env.example`** — `SCOUT_RSS_FEEDS`,
   `CRMLS_API_KEY`, `CRMLS_MEMBER_ID`, `REALESTATEAPI_KEY`,
   `BATCHDATA_API_KEY`, `ALERT_PHONE`. None is declared, so the config gap is
   invisible.
3. **Add `max_area_divergence_bps` to the valuation policy**, defaulting to
   ±10% per industry practice, and raise a `review_reason` when exceeded rather
   than silently accepting. Closes B-3 in the engine's own idiom.
4. **Tighten the defaults toward practice** — `max_distance_meters` 5,000 → 800,
   `max_age_days` 365 → 180 — and let the existing `review_reasons` mechanism
   report when a thin market forces a widening. This makes Bob *say* when it is
   outside normal practice, which it currently does not.
5. **Require renovated comps for `after_repair`.** The real fix for B-4:
   `purpose='after_repair'` should demand comps attested as post-renovation
   finish, and reject the request otherwise. Pairs with the Rehab Engine spec's
   Rule 11.2.
6. **Report coverage as a stratified gap**, not a count — by price band at
   minimum, since that is where the literature says coverage breaks and where
   Bob's worst case sits.
7. **Conformal prediction, when a local calibration set exists.** Right
   technique, blocked on San Joaquin sales with verified outcomes. Do not
   attempt it on Iowa data and call the result California accuracy.

Items 1–5 are small, local, and testable. Item 7 is the real answer and it
waits on data.

---

## 9. The honest summary

**What the research says we are doing right:** the two-part AVM architecture is
correct and both halves exist. Sold-only comps, explicit per-category
adjustments with evidence references, refusing to quote under wide dispersion,
and default-false quote authority are all stronger than the practitioner
guidance I found. The leakage controls in the benchmark are better than most
published work.

**What it says we are doing wrong:** comp policy is 2–6× looser than practice
with no feature-divergence limit at all; ARV is market value relabeled rather
than a renovated-comp valuation; and uncertainty is reported as a sample range
that cannot be calibrated by construction.

**What it says about the grade:** 9.86% against a ~7% off-market
state-of-the-art is a much better showing than I credited. **The valuation
method is closer to adequate than the surrounding system is.** The binding
constraints are the Rehab Engine, the comp policy, and local sales data — not
the estimator.

---

## Sources

- [Zestimate accuracy](https://irinanorrell.com/how-accurate-is-zillows-zestimate/) · [Redfin Estimate accuracy](https://houwzer.com/blog/redfin-estimate-info/) · [Redfin vs Zillow](https://www.realestateskills.com/blog/redfin-vs-zillow) · [HouseCanary/CoreLogic comparison](https://think4ai.com/ai-property-valuation-tools-2026/)
- [Automated valuation model (Wikipedia)](https://en.wikipedia.org/wiki/Automated_valuation_model)
- [ARV methodology — REIkit](https://www.reikit.com/house-flipping-guide/arv-real-estate-meaning-calculate-after-repair-value) · [Real Estate Skills ARV calculator](https://www.realestateskills.com/blog/arv-calculator) · [Understanding ARV (PDF)](https://thehardmoneyco.com/wp-content/uploads/2022/08/UARV_Presentation_10.7.20.pdf) · [ARV formula](https://www.fool.com/terms/a/arv-formula/)
- [Locally weighted conformal prediction for AVMs (arXiv)](https://arxiv.org/html/2312.06531v1) · [Towards Better Uncertainty Quantification in AVMs (Springer)](https://link.springer.com/article/10.1007/s11146-024-10002-7) · [Normalized nonconformity measures for AVMs (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0957417421006059) · [Inductive conformal prediction intro (arXiv)](https://arxiv.org/pdf/2206.11810)
- [property-avm-xgboost](https://github.com/ainifadillahn/property-avm-xgboost) · [california-housing-conformal-prediction](https://github.com/AubinEspinas/california-housing-conformal-prediction) · [hedonic-pricing topic](https://github.com/topics/hedonic-pricing) · [riyadh-housing-valuation](https://github.com/yasirAlot/riyadh-housing-valuation) · [AutomaticValuationModel](https://github.com/jayshah5696/AutomaticValuationModel)
- [Real estate data providers compared](https://www.olostep.com/blog/best-real-estate-data-providers) · [Off-market property tools](https://resimpli.com/blog/best-tools-to-find-off-market-properties-guide/) · [PropStream vs BatchLeads vs DealMachine](https://www.jamilacademy.com/blog/propstream-vs-batchleads-vs-dealmachine) · [Probate data tools](https://www.probatedata.com/blog/best-property-data-tools-for-off-market-real-estate-prospecting-2026)
