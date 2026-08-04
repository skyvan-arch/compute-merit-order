"""Tests for the hourly curtailment-option model.

These exist because the previous annual-mean formulation produced a false
conclusion: averaging away the price tail made every zone look permanently
economic. The tests below pin the property that broke it — that a single
extreme hour must survive aggregation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from models import curtailment_option
from models.merit_order import ComputeBenchmark

BENCHMARK = ComputeBenchmark(
    benchmark_id="test_spot",
    label="test spot",
    usd_per_gpu_hour=1.00,
    basis="test",
    source_url="https://example.test",
)


def _hourly(prices_eur_mwh: list[float], bzn: str = "BE") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                [3600 * i for i in range(len(prices_eur_mwh))], unit="s", utc=True
            ),
            "price_eur_mwh": prices_eur_mwh,
            "bzn": [bzn] * len(prices_eur_mwh),
            "zone_name": ["Belgium"] * len(prices_eur_mwh),
            "country": ["BE"] * len(prices_eur_mwh),
            "role": ["constrained"] * len(prices_eur_mwh),
            "license": ["CC BY 4.0 test"] * len(prices_eur_mwh),
        }
    )


def test_a_single_extreme_hour_is_not_averaged_away() -> None:
    """The failure mode of the previous model, pinned.

    Mean price here is modest, but one hour is far above the strike. An
    annual-mean model reports zero; the hourly model must not.
    """
    # 1 EUR/MWh for 99 hours, then one spike. FX 1.0, 1.0 kW, no opex.
    prices = [1.0] * 99 + [2000.0]
    costed = curtailment_option.hourly_avoidable_cost(
        _hourly(prices), fx_usd_per_eur=1.0, opex_usd_per_gpu_hour=0.0, delivered_kw=1.0
    )
    # Mean avoidable cost is ~0.02 USD/GPU-h, far below the 1.00 strike.
    assert costed["avoidable_cost_usd_gpu_hour"].mean() < BENCHMARK.usd_per_gpu_hour

    out = curtailment_option.option_value_by_zone(costed, BENCHMARK)
    assert len(out) == 1
    row = out.iloc[0]
    # The spike hour costs 2.0 USD/GPU-h against a 1.00 strike -> 1.00 avoided.
    assert row["hours_uneconomic"] == 1
    assert row["intrinsic_value_usd_per_gpu_sample"] == pytest.approx(1.00)
    assert row["option_value_usd_per_gpu_year"] > 0


def test_option_is_worthless_when_never_in_the_money() -> None:
    costed = curtailment_option.hourly_avoidable_cost(
        _hourly([10.0] * 50), fx_usd_per_eur=1.0, opex_usd_per_gpu_hour=0.0, delivered_kw=1.0
    )
    row = curtailment_option.option_value_by_zone(costed, BENCHMARK).iloc[0]
    assert row["hours_uneconomic"] == 0
    assert row["option_value_usd_per_gpu_year"] == pytest.approx(0.0)


def test_value_is_one_sided_gains_never_offset_losses() -> None:
    """Curtailment is a right, not an obligation: cheap hours add no value."""
    cheap_then_spike = _hourly([1.0] * 99 + [2000.0])
    very_cheap_then_spike = _hourly([-500.0] * 99 + [2000.0])

    kwargs = {"fx_usd_per_eur": 1.0, "opex_usd_per_gpu_hour": 0.0, "delivered_kw": 1.0}
    a = curtailment_option.option_value_by_zone(
        curtailment_option.hourly_avoidable_cost(cheap_then_spike, **kwargs), BENCHMARK
    ).iloc[0]
    b = curtailment_option.option_value_by_zone(
        curtailment_option.hourly_avoidable_cost(very_cheap_then_spike, **kwargs), BENCHMARK
    ).iloc[0]

    # Deeply negative prices do not reduce the value of the right to curtail.
    assert a["intrinsic_value_usd_per_gpu_sample"] == pytest.approx(
        b["intrinsic_value_usd_per_gpu_sample"]
    )


def test_higher_opex_can_only_increase_option_value() -> None:
    prices = [1.0] * 99 + [900.0]
    values = []
    for opex in (0.0, 0.2, 0.5):
        costed = curtailment_option.hourly_avoidable_cost(
            _hourly(prices), fx_usd_per_eur=1.0, opex_usd_per_gpu_hour=opex, delivered_kw=1.0
        )
        row = curtailment_option.option_value_by_zone(costed, BENCHMARK).iloc[0]
        values.append(float(row["option_value_usd_per_gpu_year"]))
    assert values == sorted(values)


def test_load_hourly_excludes_non_redistributable_zones(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The licence gate must fail closed on the hourly series too.

    /data/interim is deliberately gitignored, but anything derived from it
    can reach /data/final, so the filter belongs here as well.
    """
    df = _hourly([10.0, 20.0])
    df.loc[0, "license"] = "for private and internal use only"
    csv = tmp_path / "hourly.csv"
    df.to_csv(csv, index=False)

    kept = curtailment_option.load_hourly(csv, publishable_only=True)
    assert len(kept) == 1
    assert "private" not in kept.iloc[0]["license"]

    everything = curtailment_option.load_hourly(csv, publishable_only=False)
    assert len(everything) == 2
