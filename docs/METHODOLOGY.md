# Methodology

This is the living technical reference for how the project is built. The
paper (`paper/main.tex`) is the polished narrative; this file is the
working document engineers and auditors should read to understand the
pipeline architecture and validation rules. Keep it in sync as phases
land — see `docs/ASSUMPTIONS.md` for the specific judgment calls made
along the way, and `docs/SOURCES.md` for where every input comes from.

## Core quantities

- **Delivered power per accelerator** (`delivered_kW`, units kW; energy per
  GPU-hour is `delivered_kW x 1 h` in kWh): accelerator TDP,
  scaled by PUE, plus a CPU/NIC/storage overhead share. Implemented in
  `config/constants.py` as a single named constant with a documented
  sensitivity range, per `docs/ASSUMPTIONS.md`.
- **Power cost per GPU-hour**: `delivered_kW × price_usd_per_kwh`.
- **Shutdown price**: power cost plus non-power marginal opex
  (staffing, bandwidth, maintenance), expressed as a range, not a point
  estimate.
- **Headroom**: `(compute_price − shutdown_price) / compute_price`.
- **Compute merit order**: all tracked capacity sorted ascending by
  marginal cost per GPU-hour, compared against a compute-price line.

See `paper/main.tex` Section 3 for the formal derivation.

## Pipeline architecture

Every data source follows the same three-stage pattern, enforced by
convention (one module per source in `pipelines/`) rather than a shared
framework, so each source's quirks stay visible rather than hidden
behind an abstraction:

1. **Raw** (`data/raw/<source>/...`): the exact API response, cached
   verbatim, with a `MANIFEST.md` next to it recording the source URL
   and fetch date for every cached file. Gitignored except the
   manifests, so raw payloads never bloat the repo but remain
   re-derivable and auditable.
2. **Interim** (`data/interim/<source>/...`): normalised, source-specific
   tidy tables (e.g. one row per hour per zone), still carrying
   `source_url` and `as_of_date` per row.
3. **Final** (`data/final/*.csv`, `data/final/hubs.geojson`): the
   published, cross-source, tidy outputs — CC-BY-4.0 licensed, and the
   only directory a downstream user should need.

Implemented for `pipelines/power_price.py` (Energy-Charts, 12 EU zones) and
`pipelines/compute_price.py` (Azure Retail Prices). `pipelines/entsoe.py`
remains as the authoritative primary power source but is token-gated and no
longer the critical path.

## Source eligibility: free data only (project constraint, set 2026-08-03)

**A source is only eligible if it is free to access and permits
redistribution of derived values.** This is a hard constraint on the
project, not a preference, and it follows from what the project claims to
be: an openly auditable dataset published under CC-BY-4.0. A number a
stranger cannot fetch and re-derive without paying for it is not
auditable, and a number we are contractually barred from republishing
cannot go into `/data/final` at all.

Concretely this rules out:

- Paywalled indices, even where the headline level is visible for free
  (Silicon Data `SDH100RT`).
- Sources whose terms prohibit redistributing raw data, regardless of
  price (GetDeploying).
- Aggregators with no published methodology and "all rights reserved"
  (ComputePrices.com).

And it favours:

- Regulatory and central-bank data (ENTSO-E, ECB).
- Vendor-published list prices and public API price lists, which are
  facts about public offers (Azure Retail Prices API — free, no
  authentication).
- Vendor documentation in open repositories (MicrosoftDocs/
  azure-compute-docs) for reference values such as accelerators per SKU.

Where a free source is weaker than a paid one, **we take the weaker
source and say so in the paper** rather than compromising
reproducibility. See `docs/SOURCES.md` for the compute-price survey where
this trade-off was made explicitly.

## Validation rules (non-negotiable)

- **No invented numbers.** A missing data point is a null value with an
  open GitHub Issue describing what would resolve it — never a
  plausible-looking placeholder. `pipelines/entsoe.py` enforces this at
  the code level: it raises `MissingTokenError` rather than returning
  fabricated rows when `ENTSOE_API_TOKEN` is absent.
- **Every non-null value needs `source_url` and `as_of_date`.** Once
  Phase 4's `hubs.geojson` schema is implemented, this will be enforced
  by a pandera/pydantic schema that fails the build on a missing field,
  per the project brief. Until then, it's enforced by convention in each
  pipeline module (every row-producing function threads these two
  fields through explicitly, rather than adding them as an
  afterthought).
- **Paper numbers must match the data.** Any numeric claim in
  `paper/main.tex` that comes from our dataset must be tagged with a
  `% CMO-CHECK: <csv> | <filters> | <column> | <value>` comment (see
  `tests/test_paper_numbers.py` for the exact syntax), which is checked
  against `data/final/*.csv` in CI. A paper section with no such tag
  contains no checkable numeric claim from our data — which is exactly
  where this draft currently stands for every section beyond DE-LU's
  pipeline status.
- **Reruns are deterministic and can run offline.** Every pipeline
  caches its raw API responses and reads from cache by default
  (`use_cache=True`), so re-running the same pull twice doesn't hit the
  network twice or produce different output from run-to-run jitter.
- **Contradictions are recorded, not silently resolved.** If two sources
  disagree on a value, both go in with a note on which was used and why
  — see `docs/SOURCES.md` for the place to record this when it comes up.

## Hub classification

Twelve hubs are classified as supply, demand, or both (Phase 4, not yet
built):

- **Supply-rich**: ERCOT West/Panhandle, Nordics, Iberia, Gulf (Saudi,
  UAE), Pacific Northwest
- **Constrained**: PJM/Northern Virginia, FLAP-D (Frankfurt, London,
  Amsterdam, Paris, Dublin), Singapore, Johor
- **Outliers**: China West (Guizhou, Sichuan, Inner Mongolia — East Data
  West Computing programme), India (Mumbai, Chennai)
- **Demand-only**: SF Bay Area — must never be modelled as supply

## Current implementation status

Populated with real data: the power leg (7 publishable EU zones of 12
collected — see `docs/WITHHELD_ZONES.md` for the licence-withheld five),
the compute leg (Azure on-demand, spot and 1/3/5-year reserved), and the
merit order joining them. The hub taxonomy above is **not** yet backed by
data and, on the evidence in the paper, does not predict cost: France
(classified constrained) is the cheapest zone in the sample and Norway NO2
(classified supply-rich) is among the dearest. Treat the taxonomy as a
hypothesis to be tested, not an input.
