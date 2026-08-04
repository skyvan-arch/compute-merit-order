"""Grid structure: what each hub's power system is actually made of.

Price is one dimension of a siting decision and, on this project's own
evidence, a small one. This module gathers the dimensions that a 24/7
gigawatt-scale load actually cares about, all from the free Energy-Charts
API (Fraunhofer ISE):

  * generation mix by production type, from which we derive the FIRM share
    -- nuclear, hydro reservoir, biomass, waste and gas are dispatchable on
    demand; wind and solar are not. A datacentre runs flat out around the
    clock, so a grid whose surplus is variable is a worse match for it than
    one whose surplus is firm, at identical average price.
  * installed capacity by type, and headroom against observed peak load,
    which is the closest free proxy for "can this grid absorb another
    gigawatt" available without interconnection-queue data.
  * net cross-border position, which distinguishes an exporter with spare
    generation from an importer whose low prices are borrowed.

Why this matters for the argument: France and Germany have nearly identical
mean wholesale prices in our sample, and completely different power systems
behind them. Any hub ranking built on price alone treats them as
interchangeable. They are not.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "grid_structure"
FINAL_DIR = REPO_ROOT / "data" / "final"

PUBLIC_POWER_URL = "https://api.energy-charts.info/public_power"
INSTALLED_POWER_URL = "https://api.energy-charts.info/installed_power"

REQUEST_DELAY_SECONDS = 6.0
MAX_RETRIES = 4

#: Production types that can be dispatched on demand. A 24/7 load cares
#: about this distinction far more than it cares about the average price.
#: Hydro run-of-river is excluded: it follows river flow, not despatch.
FIRM_TYPES: frozenset[str] = frozenset(
    {
        "Nuclear",
        "Hydro water reservoir",
        "Hydro pumped storage",
        "Fossil gas",
        "Fossil hard coal",
        "Fossil brown coal / lignite",
        "Fossil oil",
        "Biomass",
        "Waste",
        "Geothermal",
        "Others",
    }
)

VARIABLE_TYPES: frozenset[str] = frozenset(
    {"Wind onshore", "Wind offshore", "Solar", "Hydro Run-of-River"}
)

#: Series that are not generation and must never be summed into a mix.
NON_GENERATION: frozenset[str] = frozenset(
    {
        "Load",
        "Residual load",
        "Renewable share of load",
        "Renewable share of generation",
        "Cross border electricity trading",
        "Hydro pumped storage consumption",
        "Battery Consumption",
        "Battery",
    }
)


@dataclass(frozen=True)
class Hub:
    """A country/zone in the study."""

    code: str
    """Energy-Charts country code."""
    name: str
    bzn: str
    """Bidding zone used by pipelines/power_price.py, for joining."""


HUBS: tuple[Hub, ...] = (
    Hub("fr", "France", "FR"),
    Hub("de", "Germany", "DE-LU"),
    Hub("nl", "Netherlands", "NL"),
    Hub("be", "Belgium", "BE"),
    Hub("at", "Austria", "AT"),
    Hub("no", "Norway", "NO2"),
    Hub("se", "Sweden", "SE4"),
    Hub("es", "Spain", "ES"),
    Hub("pt", "Portugal", "PT"),
    Hub("fi", "Finland", "FI"),
    Hub("it", "Italy", "IT-North"),
    Hub("pl", "Poland", "PL"),
    Hub("ch", "Switzerland", "CH"),
    Hub("ie", "Ireland", "IE"),
    Hub("dk", "Denmark", "DK"),
)


class GridFetchError(RuntimeError):
    """Raised when a hub cannot be fetched. Never swallowed into fake data."""


def _get(url: str, params: dict[str, Any], cache_path: Path, *, use_cache: bool) -> dict[str, Any]:
    """Throttled, cached GET returning parsed JSON."""
    if use_cache and cache_path.exists():
        cached: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached

    last = ""
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(REQUEST_DELAY_SECONDS * (attempt + 1))
        response = requests.get(url, params=params, timeout=120)
        if response.status_code == 429:
            last = "rate limited (429)"
            continue
        if response.status_code != 200:
            raise GridFetchError(f"HTTP {response.status_code} from {url} {params}")
        payload: dict[str, Any] = response.json()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = cache_path.parent / "MANIFEST.md"
        with manifest.open("a", encoding="utf-8") as f:
            f.write(f"- {cache_path.name}: {url} {params} (fetched {datetime.now(UTC):%Y-%m-%d})\n")
        time.sleep(REQUEST_DELAY_SECONDS)
        return payload
    raise GridFetchError(f"{url} {params}: {last} after {MAX_RETRIES} attempts")


def fetch_generation(hub: Hub, start: str, end: str, *, use_cache: bool = True) -> dict[str, Any]:
    return _get(
        PUBLIC_POWER_URL,
        {"country": hub.code, "start": start, "end": end},
        RAW_DIR / f"public_power_{hub.code}_{start}_{end}.json",
        use_cache=use_cache,
    )


def fetch_installed(hub: Hub, *, use_cache: bool = True) -> dict[str, Any]:
    return _get(
        INSTALLED_POWER_URL,
        {"country": hub.code, "time_step": "yearly"},
        RAW_DIR / f"installed_power_{hub.code}.json",
        use_cache=use_cache,
    )


def summarise_generation(payload: dict[str, Any], hub: Hub, source_url: str) -> dict[str, Any]:
    """Derive firm/variable shares, load and net import position for one hub."""
    series = {s["name"]: s["data"] for s in payload.get("production_types", [])}
    if not series:
        raise GridFetchError(f"{hub.code}: no production_types in response")

    def mean_of(name: str) -> float:
        vals = [v for v in series.get(name, []) if v is not None]
        return float(sum(vals) / len(vals)) if vals else 0.0

    def peak_of(name: str) -> float:
        vals = [v for v in series.get(name, []) if v is not None]
        return float(max(vals)) if vals else 0.0

    generation_types = [n for n in series if n not in NON_GENERATION]
    firm_mw = sum(mean_of(n) for n in generation_types if n in FIRM_TYPES)
    variable_mw = sum(mean_of(n) for n in generation_types if n in VARIABLE_TYPES)
    total_gen_mw = firm_mw + variable_mw

    mean_load = mean_of("Load")
    peak_load = peak_of("Load")
    # Positive cross-border trading = net export in the Energy-Charts sign
    # convention; negative = net import.
    net_trade = mean_of("Cross border electricity trading")

    return {
        "hub_code": hub.code,
        "hub_name": hub.name,
        "bzn": hub.bzn,
        "mean_load_mw": mean_load,
        "peak_load_mw": peak_load,
        "mean_generation_mw": total_gen_mw,
        "firm_generation_mw": firm_mw,
        "variable_generation_mw": variable_mw,
        "firm_share_of_generation": firm_mw / total_gen_mw if total_gen_mw else float("nan"),
        "nuclear_mw": mean_of("Nuclear"),
        "nuclear_share_of_load": mean_of("Nuclear") / mean_load if mean_load else float("nan"),
        "hydro_reservoir_mw": mean_of("Hydro water reservoir"),
        "wind_solar_mw": mean_of("Wind onshore") + mean_of("Wind offshore") + mean_of("Solar"),
        "net_cross_border_mw": net_trade,
        "net_export_share_of_load": net_trade / mean_load if mean_load else float("nan"),
        "generation_source_url": source_url,
    }


def summarise_installed(payload: dict[str, Any], hub: Hub, source_url: str) -> dict[str, Any]:
    """Latest-year installed capacity by type, in GW."""
    times = payload.get("time", [])
    if not times:
        raise GridFetchError(f"{hub.code}: no time axis in installed_power response")
    idx = len(times) - 1

    total = 0.0
    firm = 0.0
    by_type: dict[str, float] = {}
    for s in payload.get("production_types", []):
        name = str(s["name"])
        data = s.get("data", [])
        if idx >= len(data) or data[idx] is None:
            continue
        value = float(data[idx])
        by_type[name] = value
        total += value
        if name in FIRM_TYPES:
            firm += value

    return {
        "hub_code": hub.code,
        "installed_year": times[idx],
        "installed_total_gw": total,
        "installed_firm_gw": firm,
        "installed_firm_share": firm / total if total else float("nan"),
        "installed_nuclear_gw": by_type.get("Nuclear", 0.0),
        "installed_source_url": source_url,
    }


def build(start: str, end: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """Fetch and summarise every hub. Returns (frame, failures)."""
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for hub in HUBS:
        try:
            gen_url = f"{PUBLIC_POWER_URL}?country={hub.code}&start={start}&end={end}"
            gen = summarise_generation(
                fetch_generation(hub, start, end, use_cache=use_cache), hub, gen_url
            )
            inst_url = f"{INSTALLED_POWER_URL}?country={hub.code}&time_step=yearly"
            inst = summarise_installed(
                fetch_installed(hub, use_cache=use_cache), hub, inst_url
            )
            row = {**gen, **{k: v for k, v in inst.items() if k != "hub_code"}}
            row["capacity_headroom_gw"] = row["installed_total_gw"] - row["peak_load_mw"] / 1000.0
            row["firm_headroom_gw"] = row["installed_firm_gw"] - row["peak_load_mw"] / 1000.0
            row["as_of_date"] = datetime.now(UTC).date().isoformat()
            row["window_start"] = start
            row["window_end"] = end
            rows.append(row)
        except (GridFetchError, requests.RequestException) as exc:
            failures.append(f"{hub.code}: {exc}")

    if not rows:
        raise GridFetchError(f"No hub returned data. Failures: {failures}")
    return pd.DataFrame(rows), failures


def write_outputs(df: pd.DataFrame) -> Path:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FINAL_DIR / "grid_structure.csv"
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    df, failures = build(args.start, args.end, use_cache=not args.no_cache)
    for failure in failures:
        print(f"[warn] {failure}")
    print(f"Wrote {write_outputs(df)} ({len(df)} hubs)")


if __name__ == "__main__":
    main()
