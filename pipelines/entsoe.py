"""ENTSO-E Transparency Platform pipeline: day-ahead prices -> monthly stats.

Pulls hourly day-ahead prices (document type A44) for a bidding zone from
the ENTSO-E Transparency Platform REST API, caches the raw XML responses,
normalises them to an hourly interim CSV, and computes monthly statistics
(mean, P10, P90, negative-price-hour count, volatility) converted from
EUR/MWh to USD/kWh using ECB monthly average reference rates.

Requires a free ENTSO-E API token in the ENTSOE_API_TOKEN environment
variable. See docs/SOURCES.md for how to obtain one. This module never
fabricates a value: if the token is missing, it raises rather than
returning placeholder data.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "entsoe"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "entsoe"
FINAL_DIR = REPO_ROOT / "data" / "final"

ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
ENTSOE_NAMESPACE = "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"

# EIC bidding zone domain codes. Extend as more European zones are added
# (see backlog issue for FR, NL, IE-SEM, GB, NO2, NO4, SE1, SE2, FI, ES, PT).
BIDDING_ZONE_EIC = {
    "DE-LU": "10Y1001A1001A82H",
}

ECB_FX_URL = (
    "https://sdw-wsrest.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A"
    "?format=csvdata&startPeriod={start}&endPeriod={end}"
)

# ENTSO-E limits a single A44 request to a 1-year window.
MAX_REQUEST_WINDOW = timedelta(days=364)


class MissingTokenError(RuntimeError):
    """Raised when ENTSOE_API_TOKEN is not set. Never caught to fabricate data."""


@dataclass(frozen=True)
class HourlyPrice:
    timestamp_utc: datetime
    zone: str
    price_eur_mwh: float
    source_url: str
    as_of_date: str


def _request_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + MAX_REQUEST_WINDOW, end)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def _cache_path(zone: str, start: datetime, end: datetime) -> Path:
    fname = f"{start:%Y%m%d}_{end:%Y%m%d}.xml"
    return RAW_DIR / zone / fname


def fetch_day_ahead_xml(
    zone: str, start: datetime, end: datetime, token: str, *, use_cache: bool = True
) -> tuple[bytes, str]:
    """Fetch (or read cached) raw A44 XML for one <=1yr window. Returns (xml_bytes, source_url)."""
    if zone not in BIDDING_ZONE_EIC:
        raise ValueError(f"Unknown bidding zone {zone!r}; add its EIC code to BIDDING_ZONE_EIC")

    domain = BIDDING_ZONE_EIC[zone]
    params = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": domain,
        "out_Domain": domain,
        "periodStart": f"{start:%Y%m%d}0000",
        "periodEnd": f"{end:%Y%m%d}0000",
    }
    source_url = (
        f"{ENTSOE_BASE_URL}?documentType=A44&in_Domain={domain}&out_Domain={domain}"
        f"&periodStart={params['periodStart']}&periodEnd={params['periodEnd']}"
    )

    cache_path = _cache_path(zone, start, end)
    if use_cache and cache_path.exists():
        return cache_path.read_bytes(), source_url

    response = requests.get(ENTSOE_BASE_URL, params=params, timeout=60)
    response.raise_for_status()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(response.content)
    manifest = cache_path.parent / "MANIFEST.md"
    with manifest.open("a", encoding="utf-8") as f:
        f.write(f"- {cache_path.name}: {source_url} (fetched {datetime.now(UTC):%Y-%m-%d})\n")
    return response.content, source_url


def parse_day_ahead_xml(xml_bytes: bytes, zone: str, source_url: str) -> list[HourlyPrice]:
    """Parse an A44 Publication_MarketDocument into hourly prices."""
    ns = {"ns": ENTSOE_NAMESPACE}
    root = ET.fromstring(xml_bytes)
    as_of_date = datetime.now(UTC).date().isoformat()

    prices: list[HourlyPrice] = []
    for timeseries in root.findall("ns:TimeSeries", ns):
        for period in timeseries.findall("ns:Period", ns):
            interval = period.find("ns:timeInterval/ns:start", ns)
            resolution = period.find("ns:resolution", ns)
            if interval is None or interval.text is None:
                continue
            if resolution is None or resolution.text != "PT60M":
                seen = resolution.text if resolution is not None else None
                raise ValueError(f"Unsupported resolution {seen!r}; only PT60M (hourly) is handled")
            period_start = datetime.strptime(interval.text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
            for point in period.findall("ns:Point", ns):
                position_el = point.find("ns:position", ns)
                price_el = point.find("ns:price.amount", ns)
                if position_el is None or price_el is None:
                    continue
                position = int(position_el.text or "0")
                price = float(price_el.text or "nan")
                timestamp = period_start + timedelta(hours=position - 1)
                prices.append(
                    HourlyPrice(
                        timestamp_utc=timestamp,
                        zone=zone,
                        price_eur_mwh=price,
                        source_url=source_url,
                        as_of_date=as_of_date,
                    )
                )
    return prices


def fetch_zone_hourly(
    zone: str, months: int, token: str, *, use_cache: bool = True
) -> pd.DataFrame:
    """Fetch `months` of trailing hourly day-ahead prices for `zone` as a DataFrame."""
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30 * months)

    all_prices: list[HourlyPrice] = []
    for window_start, window_end in _request_windows(start, end):
        xml_bytes, source_url = fetch_day_ahead_xml(
            zone, window_start, window_end, token, use_cache=use_cache
        )
        all_prices.extend(parse_day_ahead_xml(xml_bytes, zone, source_url))

    df = pd.DataFrame(
        [
            {
                "timestamp_utc": p.timestamp_utc,
                "zone": p.zone,
                "price_eur_mwh": p.price_eur_mwh,
                "source_url": p.source_url,
                "as_of_date": p.as_of_date,
            }
            for p in all_prices
        ]
    )
    return df.sort_values("timestamp_utc").drop_duplicates(subset=["timestamp_utc", "zone"])


def write_interim(df: pd.DataFrame, zone: str) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / f"{zone}_hourly.csv"
    df.to_csv(out_path, index=False)
    return out_path


def fetch_ecb_monthly_fx(
    start_month: str, end_month: str, *, use_cache: bool = True
) -> pd.DataFrame:
    """Fetch ECB monthly average EUR->USD reference rate for [start_month, end_month] (YYYY-MM)."""
    cache_path = RAW_DIR.parent / "ecb_fx" / f"{start_month}_{end_month}.csv"
    source_url = ECB_FX_URL.format(start=start_month, end=end_month)

    if use_cache and cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
    else:
        response = requests.get(source_url, timeout=30)
        response.raise_for_status()
        text = response.text
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        manifest = cache_path.parent / "MANIFEST.md"
        with manifest.open("a", encoding="utf-8") as f:
            f.write(f"- {cache_path.name}: {source_url} (fetched {datetime.now(UTC):%Y-%m-%d})\n")

    from io import StringIO

    raw = pd.read_csv(StringIO(text))
    fx = raw[["TIME_PERIOD", "OBS_VALUE"]].rename(
        columns={"TIME_PERIOD": "month", "OBS_VALUE": "usd_per_eur"}
    )
    fx["source_url"] = source_url
    return fx


def compute_monthly_stats(hourly_df: pd.DataFrame, fx_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate hourly EUR/MWh prices into monthly stats, converted to USD/kWh."""
    df = hourly_df.copy()
    df["month"] = df["timestamp_utc"].dt.strftime("%Y-%m")

    grouped = df.groupby(["zone", "month"])["price_eur_mwh"]
    stats = grouped.agg(
        mean_eur_mwh="mean",
        p10_eur_mwh=lambda s: s.quantile(0.10),
        p90_eur_mwh=lambda s: s.quantile(0.90),
        volatility_eur_mwh="std",
        negative_hours=lambda s: int((s < 0).sum()),
        hour_count="count",
    ).reset_index()

    meta = (
        df.groupby(["zone", "month"])
        .agg(source_url=("source_url", "first"), as_of_date=("as_of_date", "first"))
        .reset_index()
    )
    stats = stats.merge(meta, on=["zone", "month"])
    stats = stats.merge(fx_df[["month", "usd_per_eur"]], on="month", how="left")

    for col in ["mean_eur_mwh", "p10_eur_mwh", "p90_eur_mwh", "volatility_eur_mwh"]:
        usd_col = col.replace("eur_mwh", "usd_kwh")
        stats[usd_col] = stats[col] * stats["usd_per_eur"] / 1000.0

    stats["confidence"] = "high"
    return stats


def write_final(stats: pd.DataFrame) -> Path:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FINAL_DIR / "entsoe_monthly_stats.csv"
    stats.to_csv(out_path, index=False)
    return out_path


def run(zone: str, months: int) -> Path:
    import os

    token = os.environ.get("ENTSOE_API_TOKEN")
    if not token:
        raise MissingTokenError(
            "ENTSOE_API_TOKEN is not set. Register a free token at "
            "https://transparency.entsoe.eu (see docs/SOURCES.md) and export it "
            "before running this pipeline. Refusing to invent data."
        )

    hourly = fetch_zone_hourly(zone, months, token)
    write_interim(hourly, zone)

    months_covered = sorted(hourly["timestamp_utc"].dt.strftime("%Y-%m").unique())
    fx = fetch_ecb_monthly_fx(months_covered[0], months_covered[-1])

    stats = compute_monthly_stats(hourly, fx)
    return write_final(stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="DE-LU", choices=sorted(BIDDING_ZONE_EIC))
    parser.add_argument("--months", type=int, default=36)
    args = parser.parse_args()
    out_path = run(args.zone, args.months)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
