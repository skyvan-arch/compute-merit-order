"""Power-price pipeline: European day-ahead prices from Energy-Charts (free).

Uses the Energy-Charts API operated by Fraunhofer ISE
(https://api.energy-charts.info), which requires no token and returns
day-ahead spot prices per bidding zone. The upstream data is published by
Bundesnetzagentur | SMARD.de under CC BY 4.0, which is compatible with this
project's own data licence — so unlike ENTSO-E (token-gated) or the
commercial power-data vendors, values derived from it can be republished in
/data/final.

Chosen over pipelines/entsoe.py for exactly that reason: see
docs/METHODOLOGY.md, "Source eligibility: free data only". The ENTSO-E
pipeline is retained because it is the authoritative primary source and
carries zones Energy-Charts does not, but it is no longer the critical path.

Resolution note: Energy-Charts returns 15-minute or hourly granularity
depending on zone and date. This module aggregates to hourly means before
computing monthly statistics, so a zone that switched resolution mid-series
does not silently change the weighting of its own monthly average.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "power_price"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "power_price"
FINAL_DIR = REPO_ROOT / "data" / "final"

ENERGY_CHARTS_URL = "https://api.energy-charts.info/price"
ENERGY_CHARTS_DOCS = "https://api.energy-charts.info/"

#: The API rate-limits aggressively (HTTP 429) on rapid successive calls.
#: Deliberately conservative — a slow correct pull beats a fast partial one.
REQUEST_DELAY_SECONDS = 6.0
MAX_RETRIES = 4


@dataclass(frozen=True)
class Zone:
    """A bidding zone in the study, with the hub role it maps to."""

    bzn: str
    name: str
    country: str
    role: str
    """'supply-rich', 'constrained', or 'other' — per the project's hub taxonomy."""


#: Zones chosen to span the supply-rich / constrained contrast the merit-order
#: thesis rests on, not merely whatever the API offers.
ZONES: tuple[Zone, ...] = (
    Zone("NO2", "Norway NO2", "NO", "supply-rich"),
    Zone("SE3", "Sweden SE3", "SE", "supply-rich"),
    Zone("SE4", "Sweden SE4", "SE", "supply-rich"),
    Zone("FI", "Finland", "FI", "supply-rich"),
    Zone("ES", "Spain", "ES", "supply-rich"),
    Zone("PT", "Portugal", "PT", "supply-rich"),
    Zone("FR", "France", "FR", "constrained"),
    Zone("DE-LU", "Germany/Luxembourg", "DE", "constrained"),
    Zone("NL", "Netherlands", "NL", "constrained"),
    Zone("BE", "Belgium", "BE", "constrained"),
    Zone("AT", "Austria", "AT", "constrained"),
    Zone("IT-North", "Italy North", "IT", "constrained"),
)


#: Substring that marks an upstream licence as redistributable. Energy-Charts
#: returns the licence PER ZONE, and they differ: German/Dutch/Belgian/French/
#: Austrian/Norwegian/SE4 data arrives as CC BY 4.0 via Bundesnetzagentur |
#: SMARD.de, while several exchange-sourced zones (Nord Pool, OMIE, GME) carry
#: "for private and internal use only". Values derived from the latter must not
#: be republished in /data/final under this project's CC-BY-4.0 data licence.
REDISTRIBUTABLE_LICENCE_MARKER = "CC BY 4.0"


class PowerFetchError(RuntimeError):
    """Raised when a zone cannot be fetched. Never swallowed into fake data."""


def is_redistributable(license_info: str) -> bool:
    """True when the upstream licence permits republishing derived values."""
    return REDISTRIBUTABLE_LICENCE_MARKER in (license_info or "")


def _cache_path(bzn: str, year: int) -> Path:
    return RAW_DIR / f"{bzn}_{year}.json"


def fetch_zone_year(
    bzn: str, year: int, *, use_cache: bool = True, delay: float = REQUEST_DELAY_SECONDS
) -> tuple[dict[str, Any], str]:
    """Fetch (or read cached) one calendar year of day-ahead prices for a zone."""
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    source_url = f"{ENERGY_CHARTS_URL}?bzn={bzn}&start={start}&end={end}"

    cache_path = _cache_path(bzn, year)
    if use_cache and cache_path.exists():
        cached: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached, source_url

    last_error = ""
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(delay * (attempt + 1))
        response = requests.get(
            ENERGY_CHARTS_URL, params={"bzn": bzn, "start": start, "end": end}, timeout=120
        )
        if response.status_code == 429:
            last_error = "rate limited (429)"
            continue
        if response.status_code != 200:
            raise PowerFetchError(f"{bzn} {year}: HTTP {response.status_code} from {source_url}")

        payload: dict[str, Any] = response.json()
        if "price" not in payload:
            raise PowerFetchError(f"{bzn} {year}: response has no 'price' field ({source_url})")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = cache_path.parent / "MANIFEST.md"
        with manifest.open("a", encoding="utf-8") as f:
            f.write(
                f"- {cache_path.name}: {source_url} "
                f"(fetched {datetime.now(UTC):%Y-%m-%d}, "
                f"licence: {payload.get('license_info', 'unknown')})\n"
            )
        time.sleep(delay)
        return payload, source_url

    raise PowerFetchError(f"{bzn} {year}: {last_error} after {MAX_RETRIES} attempts")


def parse_payload(payload: dict[str, Any], zone: Zone, source_url: str) -> pd.DataFrame:
    """Turn one Energy-Charts response into an hourly-mean price frame."""
    seconds = payload.get("unix_seconds") or []
    prices = payload.get("price") or []
    if len(seconds) != len(prices):
        raise PowerFetchError(
            f"{zone.bzn}: {len(seconds)} timestamps but {len(prices)} prices in {source_url}"
        )
    if not seconds:
        raise PowerFetchError(f"{zone.bzn}: empty series from {source_url}")

    df = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(seconds, unit="s", utc=True),
            "price_eur_mwh": pd.to_numeric(prices, errors="coerce"),
        }
    ).dropna(subset=["price_eur_mwh"])

    # Collapse whatever native resolution the zone reports onto a common
    # hourly grid, so mixed-resolution years are not silently mis-weighted.
    df = df.set_index("timestamp_utc").resample("1h")["price_eur_mwh"].mean().dropna().reset_index()
    df["bzn"] = zone.bzn
    df["zone_name"] = zone.name
    df["country"] = zone.country
    df["role"] = zone.role
    df["source_url"] = source_url
    df["license"] = payload.get("license_info", "")
    return df


def fetch_all(
    years: list[int], zones: tuple[Zone, ...] = ZONES, *, use_cache: bool = True
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch every zone/year. Returns (hourly frame, list of failure messages)."""
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for zone in zones:
        for year in years:
            try:
                payload, source_url = fetch_zone_year(zone.bzn, year, use_cache=use_cache)
                frames.append(parse_payload(payload, zone, source_url))
            except (PowerFetchError, requests.RequestException) as exc:
                # Recorded, not silently dropped: a zone missing from the
                # output must be explainable, never mistaken for zero.
                failures.append(f"{zone.bzn} {year}: {exc}")

    if not frames:
        raise PowerFetchError(f"No zone returned data. Failures: {failures}")
    return pd.concat(frames, ignore_index=True), failures


def monthly_stats(hourly: pd.DataFrame, fx_usd_per_eur: float, fx_source_url: str) -> pd.DataFrame:
    """Monthly mean/P10/P90/volatility/negative-hours per zone, in USD/kWh."""
    df = hourly.copy()
    df["month"] = df["timestamp_utc"].dt.strftime("%Y-%m")

    grouped = df.groupby(["bzn", "zone_name", "country", "role", "month"])["price_eur_mwh"]
    stats = grouped.agg(
        mean_eur_mwh="mean",
        p10_eur_mwh=lambda s: s.quantile(0.10),
        p90_eur_mwh=lambda s: s.quantile(0.90),
        volatility_eur_mwh="std",
        negative_hours=lambda s: int((s < 0).sum()),
        hour_count="count",
    ).reset_index()

    meta = (
        df.groupby(["bzn", "month"])
        .agg(source_url=("source_url", "first"), license=("license", "first"))
        .reset_index()
    )
    stats = stats.merge(meta, on=["bzn", "month"])

    for col in ("mean", "p10", "p90", "volatility"):
        stats[f"{col}_usd_kwh"] = stats[f"{col}_eur_mwh"] * fx_usd_per_eur / 1000.0

    stats["fx_usd_per_eur"] = fx_usd_per_eur
    stats["fx_source_url"] = fx_source_url
    stats["as_of_date"] = datetime.now(UTC).date().isoformat()
    stats["confidence"] = "high"
    return stats.sort_values(["bzn", "month"]).reset_index(drop=True)


def zone_summary(stats: pd.DataFrame) -> pd.DataFrame:
    """Collapse monthly stats to one row per zone over the whole window.

    Weighted by hour_count, NOT a flat mean of monthly means. The sample
    contains partial boundary months -- the first is a 1-hour stub from the
    prior year's final UTC hour -- and giving a 1-hour month the same weight
    as a 744-hour month distorts every zone mean by up to 17% and can reorder
    zones that sit within a fraction of a percent of each other.
    """
    stats = stats.copy()
    stats["_weighted_usd"] = stats["mean_usd_kwh"] * stats["hour_count"]
    stats["_weighted_eur"] = stats["mean_eur_mwh"] * stats["hour_count"]

    grouped = stats.groupby(["bzn", "zone_name", "country", "role"])
    summary = grouped.agg(
        _sum_weighted_usd=("_weighted_usd", "sum"),
        _sum_weighted_eur=("_weighted_eur", "sum"),
        min_month_usd_kwh=("mean_usd_kwh", "min"),
        max_month_usd_kwh=("mean_usd_kwh", "max"),
        negative_hours=("negative_hours", "sum"),
        hour_count=("hour_count", "sum"),
        months_covered=("month", "nunique"),
        source_url=("source_url", "first"),
        license=("license", "first"),
        fx_usd_per_eur=("fx_usd_per_eur", "first"),
        fx_source_url=("fx_source_url", "first"),
        as_of_date=("as_of_date", "first"),
    ).reset_index()

    summary["mean_usd_kwh"] = summary["_sum_weighted_usd"] / summary["hour_count"]
    summary["mean_eur_mwh"] = summary["_sum_weighted_eur"] / summary["hour_count"]
    summary = summary.drop(columns=["_sum_weighted_usd", "_sum_weighted_eur"])
    summary["confidence"] = "high"
    return summary.sort_values("mean_usd_kwh").reset_index(drop=True)


def split_by_licence(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition rows into (publishable, withheld) on the upstream licence."""
    mask = df["license"].apply(is_redistributable)
    return df[mask].copy(), df[~mask].copy()


def write_licence_report(withheld: pd.DataFrame, path: Path) -> Path:
    """Record which zones were withheld and why — never a silent omission."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Zones withheld from /data/final on licence grounds",
        "",
        "Energy-Charts returns a licence per bidding zone. Zones whose upstream",
        "licence does not permit redistribution are fetched and analysed locally",
        "but their derived values are NOT published here, because this project",
        "publishes /data/final under CC-BY-4.0.",
        "",
        "To reproduce the full-sample figures, run the pipeline yourself: the",
        "raw responses are cached under data/raw/power_price/ and the restriction",
        "is on redistribution, not on your own use.",
        "",
    ]
    if withheld.empty:
        lines.append("_No zones currently withheld._")
    else:
        lines.append("| Zone | Upstream licence |")
        lines.append("| --- | --- |")
        for bzn, licence in withheld[["bzn", "license"]].drop_duplicates().itertuples(index=False):
            lines.append(f"| {bzn} | {licence} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_outputs(hourly: pd.DataFrame, stats: pd.DataFrame, summary: pd.DataFrame) -> list[Path]:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_DIR.mkdir(parents=True, exist_ok=True)

    # interim/ is local working data and keeps every zone; final/ is the
    # published artefact and must carry only redistributable ones.
    hourly_path = INTERIM_DIR / "eu_hourly_prices.csv"
    hourly.to_csv(hourly_path, index=False)

    publishable_stats, withheld_stats = split_by_licence(stats)
    publishable_summary, _ = split_by_licence(summary)

    stats_path = FINAL_DIR / "power_price_monthly.csv"
    summary_path = FINAL_DIR / "power_price_by_zone.csv"
    publishable_stats.to_csv(stats_path, index=False)
    publishable_summary.to_csv(summary_path, index=False)

    report_path = write_licence_report(withheld_stats, REPO_ROOT / "docs" / "WITHHELD_ZONES.md")
    return [hourly_path, stats_path, summary_path, report_path]


def run(
    years: list[int], fx_usd_per_eur: float, fx_source_url: str, *, use_cache: bool = True
) -> list[Path]:
    hourly, failures = fetch_all(years, use_cache=use_cache)
    for failure in failures:
        print(f"[warn] {failure}")
    stats = monthly_stats(hourly, fx_usd_per_eur, fx_source_url)
    summary = zone_summary(stats)

    withheld = sorted(set(stats.loc[~stats["license"].apply(is_redistributable), "bzn"]))
    if withheld:
        print(
            f"[licence] {len(withheld)} zone(s) analysed locally but withheld from "
            f"/data/final: {', '.join(withheld)} — see docs/WITHHELD_ZONES.md"
        )
    return write_outputs(hourly, stats, summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[date.today().year - 1])
    parser.add_argument("--fx-usd-per-eur", type=float, required=True)
    parser.add_argument("--fx-source-url", required=True)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    paths = run(
        args.years,
        args.fx_usd_per_eur,
        args.fx_source_url,
        use_cache=not args.no_cache,
    )
    for path in paths:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
