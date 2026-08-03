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
`paper/main.tex`, Limitations) — document exactly which series is used
and its caveats here once selected.
