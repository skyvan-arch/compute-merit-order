"""Tests for pipelines.compute_price.

The fixture is a real Azure Retail Prices response for
Standard_ND96isr_H100_v5 in eastus, captured 2026-08-03 and trimmed to one
row per (skuName, OS, type) combination. It is used to pin the filtering
rules — the whole correctness risk in this pipeline is picking the wrong
row out of the twelve Azure returns for a single SKU.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from config.gpu_skus import AZURE_GPU_SKUS, sku_by_arm_name
from pipelines import compute_price

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "azure_h100_eastus_sample.json"
H100_SKU_NAME = "Standard_ND96isr_H100_v5"


@pytest.fixture
def payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_basket_entries_all_carry_a_source() -> None:
    """No accelerator count may enter the basket without provenance."""
    for sku in AZURE_GPU_SKUS:
        assert sku.source_url.startswith("https://"), sku.arm_sku_name
        assert sku.as_of_date, sku.arm_sku_name
        assert sku.accelerator_count > 0, sku.arm_sku_name


def test_parse_selects_linux_on_demand_spot_and_reserved(
    payload: dict[str, object],
) -> None:
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None

    observations = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://example.test/prices"
    )

    by_type = {o.price_type: o for o in observations}
    assert set(by_type) == {"on_demand", "spot", "reserved_1yr"}

    # Reservation rows quote the term TOTAL; 551221 over 1 year of 8760 h on
    # 8 accelerators = 7.8656 USD per GPU-hour.
    reserved = by_type["reserved_1yr"]
    assert reserved.usd_per_instance_hour == pytest.approx(551221.0 / 8760)
    assert reserved.usd_per_gpu_hour == pytest.approx(7.8656, abs=1e-3)

    on_demand = by_type["on_demand"]
    assert on_demand.usd_per_instance_hour == pytest.approx(98.32)
    # 98.32 for 8 accelerators = 12.29 per GPU-hour
    assert on_demand.usd_per_gpu_hour == pytest.approx(12.29)
    assert on_demand.accelerator_count == 8
    assert on_demand.accelerator_model == "NVIDIA H100"


def test_windows_rows_are_excluded(payload: dict[str, object]) -> None:
    """Windows pricing embeds OS licensing, which is not an accelerator cost."""
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None
    observations = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://example.test/prices"
    )
    # The Windows on-demand row is 102.736; it must not appear at any price.
    assert all(o.usd_per_instance_hour != pytest.approx(102.736) for o in observations)


def test_reservation_totals_are_never_published_raw(
    payload: dict[str, object],
) -> None:
    """The term total (551221.0) must be divided down, never emitted as-is."""
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None
    observations = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://example.test/prices"
    )
    assert all(o.usd_per_instance_hour < 1000 for o in observations)


def test_parsing_is_deterministic_for_a_fixed_as_of(
    payload: dict[str, object],
) -> None:
    """Same cache + same as_of must give the same answer on any day.

    Previously as_of_date and the expiry cutoff were read from the wall
    clock at parse time, so re-parsing an unchanged cache drifted.
    """
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None
    moment = datetime(2026, 8, 3, tzinfo=UTC)
    first = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://x", as_of=moment
    )
    second = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://x", as_of=moment
    )
    assert first == second
    assert all(o.as_of_date == "2026-08-03" for o in first)


def test_low_priority_rows_are_excluded(payload: dict[str, object]) -> None:
    """Low Priority is a distinct product from Spot; blending them would lie."""
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None
    observations = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://example.test/prices"
    )
    assert all(o.usd_per_instance_hour != pytest.approx(19.664) for o in observations)


def test_expired_rows_are_excluded() -> None:
    """A row whose effectiveEndDate has passed is history, not a current price."""
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None
    expired_payload = {
        "Items": [
            {
                "type": "Consumption",
                "unitOfMeasure": "1 Hour",
                "productName": "Virtual Machines NDsr H100 v5 Series",
                "skuName": "ND96isrH100v5",
                "retailPrice": 98.32,
                "currencyCode": "USD",
                "effectiveStartDate": "2023-12-01T00:00:00Z",
                "effectiveEndDate": "2024-01-01T00:00:00Z",
            }
        ]
    }
    observations = compute_price.parse_price_rows(
        expired_payload, sku, region="eastus", price_source_url="https://example.test/prices"
    )
    assert observations == []


def test_every_observation_carries_both_source_urls(payload: dict[str, object]) -> None:
    """Price provenance and accelerator-count provenance are tracked separately."""
    sku = sku_by_arm_name(H100_SKU_NAME)
    assert sku is not None
    observations = compute_price.parse_price_rows(
        payload, sku, region="eastus", price_source_url="https://example.test/prices"
    )
    for o in observations:
        assert o.price_source_url
        assert o.accelerator_count_source_url.startswith("https://")
        assert o.as_of_date


def test_summarise_reports_per_segment_never_blended() -> None:
    df = pd.DataFrame(
        [
            {
                "provider": "azure",
                "segment": "hyperscaler",
                "accelerator_model": "NVIDIA H100",
                "region": "eastus",
                "price_type": "on_demand",
                "usd_per_gpu_hour": 12.29,
                "as_of_date": "2026-08-03",
                "price_source_url": "https://example.test/prices",
            },
            {
                "provider": "examplecloud",
                "segment": "neocloud",
                "accelerator_model": "NVIDIA H100",
                "region": "eastus",
                "price_type": "on_demand",
                "usd_per_gpu_hour": 2.50,
                "as_of_date": "2026-08-03",
                "price_source_url": "https://example.test/prices",
            },
            {
                "provider": "azure",
                "segment": "hyperscaler",
                "accelerator_model": "NVIDIA H100",
                "region": "eastus",
                "price_type": "spot",
                "usd_per_gpu_hour": 2.27,
                "as_of_date": "2026-08-03",
                "price_source_url": "https://example.test/prices",
            },
        ]
    )
    summary = compute_price.summarise_by_model(df)

    # Two segments stay separate rather than averaging to a meaningless ~7.
    on_demand_rows = summary[summary["price_type"] == "on_demand"]
    assert len(on_demand_rows) == 2
    assert set(on_demand_rows["segment"]) == {"hyperscaler", "neocloud"}
    hyperscaler = on_demand_rows[on_demand_rows["segment"] == "hyperscaler"].iloc[0]
    # Spot must not contaminate the on-demand aggregate.
    assert hyperscaler["mean_usd_per_gpu_hour"] == pytest.approx(12.29)
