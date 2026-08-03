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

## Not yet decided (flagged, not guessed)

The following are named as constants in the project brief but have not
been implemented or chosen yet, because Phase 3 (the model) has not
started this session:

- `delivered_kW` (accelerator TDP × PUE + overhead share) — no default
  has been set in code yet. When it is, it must live as a single named
  constant with the 0.9–1.4 sensitivity range from the project brief,
  not duplicated across modules.
- Non-power marginal opex range for the shutdown price calculation.
- PUE default (industry-typical ~1.25 is mentioned in the project brief
  as a planning figure, but is not yet wired into any code — do not
  treat it as adopted until it appears in `config/`).

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
