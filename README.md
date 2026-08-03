# Compute Merit Order

An open, reproducible dataset and research paper on where AI compute is
economic to run, and what binds first: chips or power.

## Thesis

A GPU cluster earns a compute price per GPU-hour and pays an electricity
cost per GPU-hour. The difference is a spread, directly analogous to the
spark spread in power markets. Below some compute price, a given fleet is
uneconomic to run — its shutdown price. Because industrial power costs vary
by roughly 3x across regions, shutdown prices vary by roughly 3x, which
implies a global merit order: as compute prices fall, capacity retires in a
predictable geographic sequence.

A second claim under test: the binding constraint on AI buildout is grid
interconnection and power availability, not chip supply.

Both claims are falsifiable from the data assembled here. See
[`paper/main.tex`](paper/main.tex) and [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
for the full derivation, and [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) /
[`docs/SOURCES.md`](docs/SOURCES.md) for exactly what went into every number.

## Repository layout

```
pipelines/      one module per data source (ENTSO-E, gridstatus, EMA/EMC, ...)
data/raw/       cached raw API responses (gitignored; manifests only)
data/interim/   normalised per-source outputs
data/final/     published tidy CSVs + GeoJSON (CC-BY-4.0, see data/LICENSE)
models/         merit order and shutdown price calculations
paper/          LaTeX source, compiled to PDF in CI
figures/        generated only by scripts in this directory, never hand-edited
tests/
docs/           METHODOLOGY.md, ASSUMPTIONS.md, SOURCES.md
```

## Status

This project is under active, multi-session construction. Progress is
tracked via GitHub Issues and milestones, not prose summaries — see the
[issues](https://github.com/skyvan-arch/compute-merit-order/issues) and
[milestones](https://github.com/skyvan-arch/compute-merit-order/milestones)
tabs.

**Phase 1 (Europe power data)** is scaffolded end-to-end for the DE-LU
bidding zone via the ENTSO-E Transparency Platform API. Real data has not
been pulled yet — that pipeline requires a free `ENTSOE_API_TOKEN`; see
[`docs/SOURCES.md`](docs/SOURCES.md) for how to obtain one.

## Rules this project holds itself to

- Never invent a number. A null value with an open GitHub Issue beats a
  plausible guess.
- Every value in `/data/final` carries a `source_url` and `as_of_date`. No
  exceptions — the build fails otherwise (see schema validation in `models/`).
- API responses are cached; reruns are deterministic and can run offline
  against the cache.
- Where a source contradicts another, both are recorded, with a note on
  which was used and why.

## Development

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy .
pre-commit install
```

## Licence

Code is MIT licensed (see [`LICENSE`](LICENSE)). Published data under
`/data/final` is CC-BY-4.0 (see [`data/LICENSE`](data/LICENSE)).
