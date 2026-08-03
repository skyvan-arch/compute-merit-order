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


def parse_price_rows(
    payload: dict[str, Any], sku: GpuSku, region: str, price_source_url: str
) -> list[PriceObservation]:
    """Extract the priceable rows for one SKU+region.

    Filters applied, each for a stated reason:
      - type == 'Consumption'   : excludes Reservation (a different product,
                                  quoted as a total not an hourly rate) and
                                  DevTestConsumption (eligibility-restricted)
      - productName excludes Windows : Windows rows embed OS licensing, which
                                  is not a cost of running an accelerator
      - unitOfMeasure == '1 Hour' : we publish an hourly series
      - currently effective      : rows whose effectiveEndDate has passed are
                                  historical and must not be read as current
    """
    as_of_date = datetime.now(UTC).date().isoformat()
    now = datetime.now(UTC)

    observations: list[PriceObservation] = []
    for item in payload.get("Items", []):
        if item.get("type") != "Consumption":
            continue
        if item.get("unitOfMeasure") != "1 Hour":
            continue
        if "windows" in str(item.get("productName", "")).lower():
            continue

        end_date = item.get("effectiveEndDate")
        if end_date and datetime.fromisoformat(end_date.replace("Z", "+00:00")) < now:
            continue

        price_type = _classify_price_type(str(item.get("skuName", "")))
        if price_type is None:
            continue

        instance_price = float(item["retailPrice"])
        observations.append(
            PriceObservation(
                provider=sku.provider,
                segment=sku.segment,
                arm_sku_name=sku.arm_sku_name,
                accelerator_model=sku.accelerator_model,
                accelerator_count=sku.accelerator_count,
                region=region,
                price_type=price_type,
                usd_per_instance_hour=instance_price,
                usd_per_gpu_hour=instance_price / sku.accelerator_count,
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
    on_demand = df[df["price_type"] == "on_demand"]
    if on_demand.empty:
        return pd.DataFrame()

    grouped = on_demand.groupby(["segment", "accelerator_model"])["usd_per_gpu_hour"]
    summary = grouped.agg(
        mean_usd_per_gpu_hour="mean",
        min_usd_per_gpu_hour="min",
        max_usd_per_gpu_hour="max",
        observation_count="count",
    ).reset_index()

    meta = (
        on_demand.groupby(["segment", "accelerator_model"])
        .agg(
            providers=("provider", lambda s: ",".join(sorted(set(s)))),
            regions=("region", lambda s: ",".join(sorted(set(s)))),
            as_of_date=("as_of_date", "first"),
            price_source_url=("price_source_url", "first"),
        )
        .reset_index()
    )
    summary = summary.merge(meta, on=["segment", "accelerator_model"])
    summary["price_basis"] = "published_on_demand_list"
    summary["confidence"] = "high"
    return summary


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
