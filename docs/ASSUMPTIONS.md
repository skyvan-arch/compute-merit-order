# Assumptions

Written as decisions are made, not reconstructed at the end. Each entry
says what was assumed, why, and where it's implemented, so it can be
challenged or revised later without archaeology.

## ENTSO-E pipeline (`pipelines/entsoe.py`)

- **Hourly resolution only (`PT60M`).** ENTSO-E day-ahead auctions moved
  some zones toward 15-minute resolution; this pipeline currently
  rejects anything other than `PT60M` (see `parse_day_ahead_xml`) rather
  than silently resampling, because resampling would mix a modeling
  choice into what's supposed to be a raw pull. If/when a zone reports
  `PT15M`, this needs an explicit, documented resampling decision, not a
  silent fallback.
- **"36 months" is approximated as `30 * months` days.** This is a
  request-window convenience, not a claim about calendar months; the
  actual monthly aggregation (`compute_monthly_stats`) groups by the
  real calendar month of each timestamp, so the approximation only
  affects how far back the trailing window reaches (by at most a few
  days), not the correctness of any individual month's statistics.
- **FX conversion uses the ECB monthly average rate for the month a
  price-hour falls in**, not a daily or hourly rate. This is a
  simplification: intra-month EUR/USD movement is folded into a single
  month-level conversion. Documented here so the paper's sensitivity
  section can be honest about it if EUR/USD volatility turns out to
  matter at the margin.
- **Negative-price hours count is a simple threshold `< 0`,** not
  netted against any negative-pricing floor rules some zones apply
  differently. If per-zone floor/cap rules turn out to matter for the
  merit-order argument, revisit per zone.
- **Cache-first, keyed by exact request window.** Re-running the
  pipeline with the same `--months` argument on the same day will reuse
  `data/raw/entsoe/<zone>/*.xml` rather than re-querying the API. This
  makes reruns deterministic and possible offline, per the project's own
  rules, but means the cache must be manually cleared (or the window
  argument changed) to force a refresh within the same day.
- **`confidence` is hardcoded to `"high"`** for every ENTSO-E row,
  because it is a first-party, open, real-time regulatory API. This
  should be revisited if any zone-specific data quality issue is found.

## Model constants (`config/constants.py`)

- **`DELIVERED_KW = 1.10`**, derived as
  `(ACCELERATOR_TDP_KW 0.700 + IT_OVERHEAD_KW 0.180) × PUE 1.25`. The
  decomposition is stated explicitly so each input can be challenged
  separately rather than arguing about the 1.10 aggregate. None of the
  three inputs is independently sourced per-site: the 700 W TDP is a
  nameplate figure, PUE 1.25 is an industry-typical planning figure (and
  operator-reported PUE is self-reported and unaudited), and the 180 W
  CPU/NIC/storage overhead share is the residual that reconciles the
  project brief's own stated TDP, PUE and 1.10 kW figures. Treat any
  conclusion sensitive to these as weak; the 0.9–1.4 sweep exists for
  exactly that reason.
- **PUE sweep bounds 1.10–1.60** are planning bounds chosen to span
  "about as good as a hyperscale facility credibly claims" to "older or
  hot-climate colocation". They are not measurements of any site.
- **Non-power marginal opex has no default and no point estimate**, per
  the project brief. It is a required argument to
  `models.spark_spread.shutdown_price()`, and
  `MARGINAL_OPEX_USD_PER_GPU_HOUR` is deliberately `None` with a test
  asserting it stays that way, so the omission cannot silently drift into
  an invented number. No public source for it has been identified — see
  issue #14. Every headroom figure this project publishes is therefore
  conditional on an assumed opex and must be labelled as such.

## The compute-price leg is weaker than the power leg (surveyed 2026-08-03)

The revenue side of the spread has no free, redistributable index
comparable to ENTSO-E. The two credible indices (Silicon Data SDH100RT,
GetDeploying) are both paywalled, and GetDeploying's terms explicitly
forbid redistributing raw data — incompatible with this project's
CC-BY-4.0 output. See `docs/SOURCES.md` for the full survey and the
recommended first-party-basket workaround.

Consequences that must not be quietly forgotten:

- The merit-order *ordering* (which hub retires first) depends mainly on
  the power leg and is comparatively robust. The *absolute level* of the
  compute price at which any given hub retires depends on the weak leg.
  These two claims deserve different confidence language in the paper.
- On-demand list price ≠ realised contract price. This is the exact
  mirror of the PPA problem on the power side, and it means both legs of
  the spread are proxies for confidential real transactions.

## Repository/tooling assumptions

- **Python 3.11+ managed via `uv`**, independent of whatever system
  Python is present. The build environment for this project had Python
  3.9 installed system-wide (Anaconda); `uv python install 3.11` was
  used instead of targeting the system interpreter, so `requires-python
  = ">=3.11"` in `pyproject.toml` is a real constraint, not aspirational.
- **`models/` and `figures/` are only added to the Hatchling wheel once
  they contain real modules.** `config/` is deliberately left out of
  packaging until Phase 3 gives it real content, to avoid empty-package
  build quirks observed during scaffolding.
- **`figures/build_all.py` skips a figure generator whose input data
  file doesn't exist yet, rather than failing the build.** This is
  intentional given only one of twelve hubs has a pipeline so far: it
  keeps `paper.yml` green as sources come online one at a time, instead
  of forcing an all-or-nothing figure build. Direct invocation of an
  individual figure script (e.g. `python -m figures.entsoe_price_figure`)
  still raises loudly if its data is missing.
