# Sources

Every value in `/data/final` carries its own `source_url` and `as_of_date`.
This file documents, per data source, where it comes from, how to get
access, and its known limitations. Update it as sources are added — do not
wait until the end of a phase.

## Power data

### ENTSO-E Transparency Platform (Europe)

- **What**: hourly day-ahead electricity prices by bidding zone (document
  type A44), via the REST API at `https://web-api.tp.entsoe.eu/api`.
- **Coverage in this repo**: DE-LU is wired up
  (`pipelines/entsoe.py`); the remaining zones (FR, NL, IE-SEM, GB, NO2,
  NO4, SE1, SE2, FI, ES, PT) are backlogged — see GitHub Issues.
- **Access**: free, but requires registration.
  1. Create an account at <https://transparency.entsoe.eu/>.
  2. Once logged in, email `transparency@entsoe.eu` with the subject
     "Restful API access" from the email address tied to your account,
     asking for API access to be enabled (this is ENTSO-E's documented
     process as of 2026 — the token is not self-service from the UI).
  3. Once enabled, generate a security token from your account settings
     page (`My Account Settings` -> `Web Api Security Token`).
  4. Export it as `ENTSOE_API_TOKEN` in your shell, or set it as a
     repository secret (`ENTSOE_API_TOKEN`) for the `refresh.yml` GitHub
     Action.
- **Status in this repo**: **no token was available in the environment
  this pipeline was built in.** `pipelines/entsoe.py` is fully
  implemented and unit-tested against a synthetic fixture
  (`tests/fixtures/entsoe_delu_sample.xml`), but has never been run
  against the live API, and `data/final/entsoe_monthly_stats.csv` does
  not exist yet. Running `python -m pipelines.entsoe --zone DE-LU` without
  the token raises `MissingTokenError` by design rather than fabricating
  output.
- **Known limits**: the API caps a single A44 request to a ~1-year
  window (`pipelines.entsoe.MAX_REQUEST_WINDOW`), so pulling 36 months
  requires chunked requests, already handled by `fetch_zone_hourly`.
  Day-ahead price is not the same as an operator's actual delivered cost
  under a bilateral PPA — see `docs/ASSUMPTIONS.md`.

### gridstatus (US ISOs — ERCOT, PJM, CAISO, MISO, SPP, BPA)

- **What**: zonal/nodal day-ahead prices via the `gridstatus` Python
  library; PJM capacity auction clearing prices as a separate series.
- **Status**: not started. Backlogged as a GitHub Issue (Phase 1, US).
- **Access**: `gridstatus` wraps each ISO's own public data portal;
  some ISOs (e.g. PJM) require a free API key from the ISO itself, not
  from `gridstatus`. Document each ISO's specific key/registration
  requirement in this file when that pipeline is built.

### EMA/EMC USEP (Singapore)

- **What**: Singapore's Uniform Singapore Energy Price, published by the
  Energy Market Authority / Energy Market Company.
- **Status**: not started. Backlogged as a GitHub Issue (Phase 4,
  Singapore hub).

### Gulf states, China, Malaysia, India

- **What**: industrial electricity tariffs; no open real-time API exists.
- **Status**: not started by design. Per project rules, these will be
  document-derived (government/utility tariff schedules, TSO reports)
  with `confidence=low`, never estimated. Each hub has (or will have) an
  open GitHub Issue naming the specific document needed.

## FX conversion

### ECB Statistical Data Warehouse (SDW)

- **What**: monthly average EUR reference rates, series
  `EXR.M.USD.EUR.SP00.A`, via
  `https://sdw-wsrest.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A`.
- **Access**: fully open, no token required.
- **Status**: wired into `pipelines/entsoe.py`
  (`fetch_ecb_monthly_fx`), used to convert EUR/MWh to USD/kWh. Not yet
  exercised end-to-end for the same reason as ENTSO-E above (no hourly
  price data to convert yet).

## Demand / constraint data (Phase 2 — not started)

- LBNL "Queued Up 2026" interconnection dataset
- interconnection.fyi / GridTracker data-center-project tables
- ERCOT Large Load Interconnection Queue (>75MW requests)
- PJM load forecast and capacity deficit figures
- ENTSO-E "Data Centres and the Power System" (April 2026 report)
- EirGrid, TenneT, RTE, Amprion, National Grid ESO connection-queue
  statements
- CBRE / DC Byte published capacity figures where free

Each is tracked as its own GitHub Issue under the Phase 2 milestone; none
have been pulled yet.

## Compute price (Phase 3 — not started)

Published GPU rental benchmarks and public compute-price indices. This
leg is explicitly the weakest in the project's methodology (see
`paper/main.tex`, Limitations).

**Survey conducted 2026-08-03 (GitHub issue #15). Headline finding: there
is no free, redistributable compute-price index of comparable quality to
the power data.** This asymmetry is structural, not incidental, and the
paper must state it plainly: the cost leg of the spread rests on open
regulatory data (ENTSO-E, ECB), while the revenue leg rests on
proprietary commercial data that this project cannot republish. Any
headroom figure inherits the weaker of the two.

Candidates evaluated:

### Silicon Data — H100 Rental Price Index (ticker SDH100RT)

- <https://www.silicondata.com/products/silicon-index/h100>
- A genuine daily-published index with a stated methodology: observations
  from "cloud providers, colocation markets, brokered cluster sales, and
  private rental platforms", standardised for machine specs, rental terms,
  platform performance and geolocation, with outlier filtering. Claims
  coverage of ~95% of tracked neo-cloud GPU providers and 100% of major
  hyperscalers, "more than 80% of the available global GPU rental market".
  Reports neo-cloud and hyperscaler segments separately.
- Level displayed as **USD 2.53 / GPU-hour** when retrieved 2026-08-03.
  **Caveat: the page does not state an as-of date for that level**, which
  by this project's own rules disqualifies it from `/data/final` as-is —
  a value without an as_of_date cannot be published here.
- **Historical series is paywalled** (subscription portal, 7-day trial).
- Verdict: cite as an external cross-check with attribution; cannot be
  redistributed, cannot be the primary series for a reproducible pipeline.

### GetDeploying — GPU Rental Price Index

- <https://getdeploying.com/gpu-price-index>, API at
  <https://getdeploying.com/api>
- Broadest coverage found: 71 providers, 98 GPU models, 43,534 weekly
  observations since July 2024, collected as often as every 15 minutes,
  panel reviewed each January and July. Index page updated 2026-08-03.
- API is **USD 299/month or USD 2,499/year**, 3,000 requests/day, bearer
  token required.
- **Terms explicitly prohibit reselling raw data feeds.** This is
  incompatible with publishing derived values under CC-BY-4.0 in
  `/data/final` without a licence negotiation.
- Verdict: best coverage, but the licence — not the price — is the
  blocker.

### ComputePrices.com

- <https://computeprices.com/> — "collected automatically from public
  sources and provider APIs". No open dataset, no repo, no stated reuse
  licence, "All rights reserved".
- Verdict: unusable as a citable primary source; no methodology published.

### Vast.ai marketplace API

- <https://docs.vast.ai/> — API key is free to obtain but requires an
  account; marketplace spot rates.
- Verdict: usable mechanically, but a decentralised spot marketplace of
  heterogeneous consumer and datacentre hardware is **not** a proxy for
  the contract price a datacentre operator actually earns. Wrong
  denominator for this model. Possible use as a lower-bound sanity check
  only.

### Recommended approach (not yet implemented)

Build a **transparent first-party index** in `pipelines/compute_price.py`:
scrape or query the *published* on-demand price pages of a fixed,
documented basket of providers (hyperscalers plus named neoclouds), record
each observation with its own `source_url` and `as_of_date`, and publish
the derived aggregate. Published prices are facts about a public offer and
are recordable with attribution; this keeps `/data/final` fully
reproducible and redistributable. The proprietary indices above then serve
as an external validation cross-check cited in the paper — never copied
into the dataset.

Two limitations of that approach must be stated in the paper up front:

1. **On-demand list price is not the realised price.** Large operators
   transact on multi-year reserved contracts at material discounts, and
   those contract prices are confidential — the same problem the power leg
   has with PPAs. Reserved-vs-on-demand discounts are publicly advertised
   by some providers and should be recorded where available.
2. **Segment dispersion is large.** Hyperscaler and neocloud list prices
   for the same accelerator differ by a multiple, not a few percent. A
   single blended index would obscure exactly the dispersion this project
   is trying to measure, so the basket must be reported by segment.
   (The specific spread quoted in secondary summaries is not recorded here
   because it has not been verified against first-party pages — do that
   before any such figure enters the paper.)
