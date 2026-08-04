"""Macro capacity: who can actually afford to build gigawatt-scale clusters.

A hub's suitability is not only physical. Building a multi-gigawatt compute
cluster is a capital project on the scale of a national infrastructure
programme, and the set of countries that can finance, permit and staff one
is smaller than the set with cheap electrons. This module pulls the free,
unauthenticated World Bank Indicators API for the macro side of that
question.

Indicators chosen deliberately:

  * NY.GDP.MKTP.CD -- GDP in current USD. A crude but honest proxy for the
    capital a jurisdiction can mobilise. A $100bn cluster is a different
    proposition against a $3tn economy than against a $300bn one.
  * EG.ELC.PROD.KH -- total electricity production, kWh. Lets us express a
    prospective cluster as a share of national generation, which is the
    number that actually decides whether a project is politically survivable.
  * EG.USE.ELEC.KH.PC -- electricity use per capita, a proxy for how much
    slack a grid has historically carried.
  * SP.POP.TOTL -- population, for per-capita normalisation.

These are national aggregates and therefore coarser than the bidding-zone
price data they will be joined to. That mismatch is real and is recorded in
docs/ASSUMPTIONS.md rather than smoothed over: Germany's GDP does not tell
you about Bavaria, and NO2 is not Norway. They are included because the
alternative -- ignoring financing capacity entirely -- implies every hub can
raise the same capital, which is plainly false.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "macro"
FINAL_DIR = REPO_ROOT / "data" / "final"

WORLD_BANK_URL = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"

#: EG.ELC.PROD.KH (total electricity production) was archived by the World
#: Bank and now 404s, so national electricity consumption is DERIVED below as
#: per-capita use x population rather than fetched. That derivation is
#: recorded here because it is an assumption, not a measurement.
INDICATORS: dict[str, str] = {
    "NY.GDP.MKTP.CD": "gdp_usd",
    "EG.USE.ELEC.KH.PC": "electricity_use_kwh_per_capita",
    "SP.POP.TOTL": "population",
    "NY.GDP.PCAP.CD": "gdp_per_capita_usd",
}

#: ISO2 codes matching pipelines/grid_structure.HUBS, plus the non-European
#: comparators the paper needs in order to say anything global.
COUNTRIES: tuple[str, ...] = (
    "FR",
    "DE",
    "NL",
    "BE",
    "AT",
    "NO",
    "SE",
    "ES",
    "PT",
    "FI",
    "IT",
    "PL",
    "CH",
    "IE",
    "DK",
    "US",
    "GB",
    "SG",
    "AE",
    "SA",
    "CN",
    "IN",
    "JP",
    "KR",
    "CA",
    "AU",
    "BR",
    "ZA",
    "MY",
    "QA",
)


class MacroFetchError(RuntimeError):
    """Raised when an indicator cannot be fetched. Never faked."""


#: The API times out on large country x year cross-products, so requests are
#: chunked. Ten is comfortably inside the limit observed in practice.
COUNTRY_CHUNK = 10
MAX_RETRIES = 3


def _fetch_chunk(
    indicator: str, chunk: tuple[str, ...], start_year: int, end_year: int, *, use_cache: bool
) -> list[dict[str, Any]]:
    """Fetch one indicator for one chunk of countries, with retries."""
    joined = ";".join(chunk)
    url = WORLD_BANK_URL.format(countries=joined, indicator=indicator)
    params = {"format": "json", "date": f"{start_year}:{end_year}", "per_page": "5000"}
    source_url = f"{url}?format=json&date={start_year}:{end_year}"

    cache_path = RAW_DIR / f"{indicator}_{'-'.join(chunk)}_{start_year}_{end_year}.json"
    if use_cache and cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        payload = None
        last_error = ""
        for _attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, params=params, timeout=90)
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = str(exc)
        if payload is None:
            raise MacroFetchError(f"{indicator} {joined}: {last_error}")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = cache_path.parent / "MANIFEST.md"
        with manifest.open("a", encoding="utf-8") as f:
            f.write(f"- {cache_path.name}: {source_url} (fetched {datetime.now(UTC):%Y-%m-%d})\n")

    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        # An archived or renamed indicator returns a message envelope rather
        # than data. Report it and continue: one dead indicator must not
        # destroy the whole macro pull.
        detail = payload[0] if isinstance(payload, list) and payload else payload
        print(f"[warn] {indicator} {joined}: no data ({detail})")
        return []

    rows: list[dict[str, Any]] = []
    for record in payload[1]:
        if record.get("value") is None:
            continue
        rows.append(
            {
                "iso2": record["country"]["id"],
                "country": record["country"]["value"],
                "year": int(record["date"]),
                "indicator": indicator,
                "value": float(record["value"]),
                "source_url": source_url,
            }
        )
    return rows


def fetch_indicator(
    indicator: str,
    countries: tuple[str, ...],
    start_year: int,
    end_year: int,
    *,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Fetch one indicator for all countries, chunked to avoid API timeouts."""
    rows: list[dict[str, Any]] = []
    for i in range(0, len(countries), COUNTRY_CHUNK):
        chunk = countries[i : i + COUNTRY_CHUNK]
        rows.extend(_fetch_chunk(indicator, chunk, start_year, end_year, use_cache=use_cache))
    return rows


def build(start_year: int = 2015, end_year: int = 2025, *, use_cache: bool = True) -> pd.DataFrame:
    """Latest available observation per country per indicator, wide format."""
    long_rows: list[dict[str, Any]] = []
    for indicator in INDICATORS:
        long_rows.extend(
            fetch_indicator(indicator, COUNTRIES, start_year, end_year, use_cache=use_cache)
        )

    long_df = pd.DataFrame(long_rows)
    if long_df.empty:
        raise MacroFetchError("World Bank returned no observations")

    # Keep the most recent year available per (country, indicator): coverage
    # lags differ by indicator, and taking a common year would discard the
    # newest GDP just because electricity data lags it.
    latest = long_df.sort_values("year").groupby(["iso2", "indicator"], as_index=False).last()

    wide = latest.pivot(index="iso2", columns="indicator", values="value")
    wide = wide.rename(columns=INDICATORS)
    years = latest.pivot(index="iso2", columns="indicator", values="year")
    years = years.rename(columns={k: f"{v}_year" for k, v in INDICATORS.items()})

    names = latest.groupby("iso2")["country"].first()
    urls = latest.groupby("iso2")["source_url"].first()

    out = wide.join(years).join(names).join(urls.rename("source_url")).reset_index()
    out["as_of_date"] = datetime.now(UTC).date().isoformat()

    if "electricity_use_kwh_per_capita" in out and "population" in out:
        # DERIVED, not measured: the World Bank archived its total-production
        # series, so national consumption is reconstructed from per-capita use
        # x population. Both legs carry their own (differing) vintage years.
        out["electricity_consumption_kwh_derived"] = (
            out["electricity_use_kwh_per_capita"] * out["population"]
        )
        # A 1 GW cluster running flat out for a year as a share of national
        # electricity consumption -- the number that decides whether a project
        # is politically survivable.
        one_gw_year_kwh = 1_000_000 * 8760.0
        out["one_gw_cluster_share_of_consumption"] = (
            one_gw_year_kwh / out["electricity_consumption_kwh_derived"]
        )
    return out.sort_values("gdp_usd", ascending=False).reset_index(drop=True)


def write_outputs(df: pd.DataFrame) -> Path:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FINAL_DIR / "macro_capacity.csv"
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    df = build(args.start_year, args.end_year, use_cache=not args.no_cache)
    print(f"Wrote {write_outputs(df)} ({len(df)} countries)")


if __name__ == "__main__":
    main()
