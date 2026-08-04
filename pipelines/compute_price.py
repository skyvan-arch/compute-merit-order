"""Compute-price pipeline: published cloud GPU list prices -> USD/GPU-hour.

Queries the Azure Retail Prices API, which is free and requires no
authentication, and converts advertised hourly VM prices into USD per
GPU-hour using the sourced accelerator counts in config/gpu_skus.py.

Why this source: a survey on 2026-08-03 (docs/SOURCES.md, GitHub issue #15)
found every existing compute-price index to be either paywalled or
contractually undistributable. A published list price is a fact about a
public offer, so it can be recorded with attribution and republished under
this project's CC-BY-4.0 data licence. This is the compute-price leg's
answer to ENTSO-E on the power leg.

What this series is NOT: the price large operators actually pay. Reserved
and negotiated contracts are materially cheaper and confidential — the
exact mirror of the PPA problem on the power side. On-demand list price is
an upper bound on realised revenue per GPU-hour, and must be described that
way wherever it is used.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from config.gpu_skus import AZURE_GPU_SKUS, AZURE_REGIONS, GpuSku

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "compute_price"
INTERIM_DIR = REPO_ROOT / "data" / "interim" / "compute_price"
FINAL_DIR = REPO_ROOT / "data" / "final"

AZURE_PRICES_URL = "https://prices.azure.com/api/retail/prices"

#: Azure's own documentation page for the API, cited as the source of method.
AZURE_PRICES_DOCS = (
    "https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices"
)


@dataclass(frozen=True)
class PriceObservation:
    """One advertised price for one SKU in one region."""

    provider: str
    segment: str
    arm_sku_name: str
    accelerator_model: str
    accelerator_count: int
    region: str
    price_type: str
    """'on_demand' or 'spot'."""
    usd_per_instance_hour: float
    usd_per_gpu_hour: float
    currency: str
    effective_start_date: str
    price_source_url: str
    accelerator_count_source_url: str
    as_of_date: str
    confidence: str


def _cache_path(arm_sku_name: str, region: str) -> Path:
    return RAW_DIR / f"{arm_sku_name}_{region}.json"


def fetch_sku_prices(
    arm_sku_name: str, region: str, *, use_cache: bool = True
) -> tuple[dict[str, Any], str]:
    """Fetch (or read cached) raw Azure retail price rows for one SKU+region."""
    query = f"armSkuName eq '{arm_sku_name}' and armRegionName eq '{region}'"
    source_url = f"{AZURE_PRICES_URL}?$filter={query}"

    cache_path = _cache_path(arm_sku_name, region)
    if use_cache and cache_path.exists():
        cached: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached, source_url

    response = requests.get(AZURE_PRICES_URL, params={"$filter": query}, timeout=60)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest = cache_path.parent / "MANIFEST.md"
    with manifest.open("a", encoding="utf-8") as f:
        f.write(f"- {cache_path.name}: {source_url} (fetched {datetime.now(UTC):%Y-%m-%d})\n")
    return payload, source_url


#: Hours in each Azure reservation term. Reservation rows quote the TOTAL
#: cost of the term, so converting to an hourly rate needs these explicitly.
#: 365-day years; Azure prices terms as whole years and does not price leap
#: days separately.
RESERVATION_TERM_HOURS: dict[str, int] = {
    "1 Year": 8_760,
    "3 Years": 26_280,
    "5 Years": 43_800,
}


def _classify_price_type(sku_name: str) -> str | None:
    """Map an Azure skuName to our price_type, or None if we don't price it.

    'Low Priority' is deliberately excluded: it is a retired/limited
    preemptible tier distinct from Spot, and mixing the two would blend two
    different products into one series.
    """
    lowered = sku_name.lower()
    if "low priority" in lowered:
        return None
    if "spot" in lowered:
        return "spot"
    return "on_demand"


def _reserved_price_type(term: str) -> str:
    """Normalise an Azure reservationTerm into a price_type label."""
    return "reserved_" + term.lower().replace(" ", "").replace("years", "yr").replace("year", "yr")


def parse_price_rows(
    payload: dict[str, Any],
    sku: GpuSku,
    region: str,
    price_source_url: str,
    *,
    as_of: datetime | None = None,
) -> list[PriceObservation]:
    """Extract the priceable rows for one SKU+region.

    `as_of` fixes both the recorded as_of_date and the cutoff used to drop
    expired price rows. It is a parameter rather than `datetime.now()` so that
    re-parsing the same cached payload gives the same answer on any day —
    without it the pipeline is not reproducible, which is a guarantee this
    project makes explicitly (docs/METHODOLOGY.md).

    Filters applied, each for a stated reason:
      - productName excludes Windows : Windows rows embed OS licensing, which
                                  is not a cost of running an accelerator
      - DevTestConsumption dropped : eligibility-restricted pricing
      - currently effective      : rows whose effectiveEndDate has passed are
                                  historical and must not be read as current

    Both Consumption rows (on-demand, spot) and Reservation rows are kept.
    Reservation rows quote the TOTAL cost of the term, so they are divided by
    the term's hours to reach a comparable hourly rate; they are the closest
    public proxy for what a committed operator actually pays.
    """
    moment = as_of or datetime.now(UTC)
    as_of_date = moment.date().isoformat()

    observations: list[PriceObservation] = []
    for item in payload.get("Items", []):
        row_type = item.get("type")
        if row_type not in {"Consumption", "Reservation"}:
            continue
        if item.get("unitOfMeasure") != "1 Hour":
            continue
        if "windows" in str(item.get("productName", "")).lower():
            continue

        end_date = item.get("effectiveEndDate")
        if end_date and datetime.fromisoformat(end_date.replace("Z", "+00:00")) < moment:
            continue

        raw_price = float(item["retailPrice"])

        if row_type == "Reservation":
            term = str(item.get("reservationTerm", ""))
            term_hours = RESERVATION_TERM_HOURS.get(term)
            if term_hours is None:
                # An unrecognised term is skipped rather than guessed at.
                continue
            price_type = _reserved_price_type(term)
            instance_hour_price = raw_price / term_hours
        else:
            classified = _classify_price_type(str(item.get("skuName", "")))
            if classified is None:
                continue
            price_type = classified
            instance_hour_price = raw_price

        observations.append(
            PriceObservation(
                provider=sku.provider,
                segment=sku.segment,
                arm_sku_name=sku.arm_sku_name,
                accelerator_model=sku.accelerator_model,
                accelerator_count=sku.accelerator_count,
                region=region,
                price_type=price_type,
                usd_per_instance_hour=instance_hour_price,
                usd_per_gpu_hour=instance_hour_price / sku.accelerator_count,
                currency=str(item.get("currencyCode", "USD")),
                effective_start_date=str(item.get("effectiveStartDate", "")),
                price_source_url=price_source_url,
                accelerator_count_source_url=sku.source_url,
                as_of_date=as_of_date,
                confidence="high",
            )
        )
    return observations


def collect_all(*, use_cache: bool = True) -> pd.DataFrame:
    """Fetch every basket SKU across every configured region."""
    rows: list[PriceObservation] = []
    for sku in AZURE_GPU_SKUS:
        for region in AZURE_REGIONS:
            payload, source_url = fetch_sku_prices(sku.arm_sku_name, region, use_cache=use_cache)
            rows.extend(parse_price_rows(payload, sku, region, source_url))

    df = pd.DataFrame([vars(r) for r in rows])
    if df.empty:
        return df
    return df.sort_values(
        ["accelerator_model", "arm_sku_name", "region", "price_type"]
    ).reset_index(drop=True)


def write_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "azure_gpu_prices.csv"
    df.to_csv(out_path, index=False)
    return out_path


def summarise_by_model(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to one on-demand USD/GPU-hour figure per accelerator model.

    Reported per segment, never blended across segments — hyperscaler and
    neocloud list prices differ by a multiple, and that dispersion is the
    thing this project is trying to measure.
    """
    if df.empty:
        return pd.DataFrame()

    # Keep ONE observation per (provider, model, region, price_type). Azure
    # lists the same machine at 1/2/4-GPU sizes (NC24/NC48/NC96); those are
    # one independent price, not three.
    #
    # NEVER dedup on the float price: Azure's own rounding makes the sizes
    # differ in the 4th decimal (northeurope A100 on-demand is 4.408000 /
    # 4.407500 / 4.407500), so a price-keyed dedup silently lets near-
    # duplicates through and skews the mean toward whichever region rounded
    # inconsistently. Sorting by accelerator_count keeps the single-GPU SKU,
    # which carries the least division rounding.
    deduped = df.sort_values("accelerator_count").drop_duplicates(
        subset=["provider", "segment", "accelerator_model", "region", "price_type"],
        keep="first",
    )

    if deduped.empty:
        return pd.DataFrame()

    keys = ["segment", "accelerator_model", "price_type"]
    grouped = deduped.groupby(keys)["usd_per_gpu_hour"]
    summary = grouped.agg(
        mean_usd_per_gpu_hour="mean",
        min_usd_per_gpu_hour="min",
        max_usd_per_gpu_hour="max",
        observation_count="count",
    ).reset_index()

    meta = (
        deduped.groupby(keys)
        .agg(
            providers=("provider", lambda s: ",".join(sorted(set(s)))),
            regions=("region", lambda s: ",".join(sorted(set(s)))),
            as_of_date=("as_of_date", "first"),
            price_source_url=("price_source_url", "first"),
        )
        .reset_index()
    )
    summary = summary.merge(meta, on=keys)
    summary["price_basis"] = "published_" + summary["price_type"].astype(str) + "_list"
    summary["confidence"] = "high"
    # Round to 4 significant figures. Publishing 4.285222222222222 from inputs
    # that disagree in the 4th figure asserts precision the data cannot carry.
    for col in (
        "mean_usd_per_gpu_hour",
        "min_usd_per_gpu_hour",
        "max_usd_per_gpu_hour",
    ):
        summary[col] = summary[col].astype(float).round(4)
    return summary.sort_values(keys).reset_index(drop=True)


def write_final(df: pd.DataFrame, summary: pd.DataFrame) -> tuple[Path, Path]:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = FINAL_DIR / "compute_price_observations.csv"
    summary_path = FINAL_DIR / "compute_price_by_model.csv"
    df.to_csv(detail_path, index=False)
    summary.to_csv(summary_path, index=False)
    return detail_path, summary_path


def run(*, use_cache: bool = True) -> tuple[Path, Path]:
    df = collect_all(use_cache=use_cache)
    if df.empty:
        raise RuntimeError("No price observations returned; refusing to write empty outputs")
    write_interim(df)
    summary = summarise_by_model(df)
    return write_final(df, summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-cache", action="store_true", help="force a refetch instead of reading data/raw"
    )
    args = parser.parse_args()
    detail_path, summary_path = run(use_cache=not args.no_cache)
    print(f"Wrote {detail_path}")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
