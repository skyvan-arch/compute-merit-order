"""Tests for the merit-order model.

Inputs are hand-built frames, not market data, so the expected values can be
checked by hand.
"""

from __future__ import annotations

import pandas as pd
import pytest

from models import merit_order


@pytest.fixture
def power() -> pd.DataFrame:
    """Three zones spanning a deliberate 3x power-cost spread."""
    return pd.DataFrame(
        [
            {
                "bzn": "NO2",
                "zone_name": "Norway NO2",
                "country": "NO",
                "role": "supply-rich",
                "mean_usd_kwh": 0.030,
            },
            {
                "bzn": "DE-LU",
                "zone_name": "Germany/Luxembourg",
                "country": "DE",
                "role": "constrained",
                "mean_usd_kwh": 0.060,
            },
            {
                "bzn": "IT-North",
                "zone_name": "Italy North",
                "country": "IT",
                "role": "constrained",
                "mean_usd_kwh": 0.090,
            },
        ]
    )


def test_ladder_is_sorted_ascending_and_ranked(power: pd.DataFrame) -> None:
    ladder = merit_order.build_ladder(power, opex_usd_per_gpu_hour=0.0, delivered_kw=1.10)

    assert list(ladder["zone_name"]) == [
        "Norway NO2",
        "Germany/Luxembourg",
        "Italy North",
    ]
    assert list(ladder["merit_rank"]) == [1, 2, 3]
    # 0.030 USD/kWh * 1.10 kW = 0.033 USD per GPU-hour
    assert ladder.iloc[0]["shutdown_price_usd_gpu_hour"] == pytest.approx(0.033)


def test_opex_shifts_every_zone_equally_and_compresses_dispersion(
    power: pd.DataFrame,
) -> None:
    """A flat opex adds a constant, so it narrows the max/min ratio."""
    no_opex = merit_order.build_ladder(power, 0.0, 1.10)
    with_opex = merit_order.build_ladder(power, 0.10, 1.10)

    ratio_without = merit_order.dispersion_ratio(no_opex, "shutdown_price_usd_gpu_hour")
    ratio_with = merit_order.dispersion_ratio(with_opex, "shutdown_price_usd_gpu_hour")

    assert ratio_without == pytest.approx(3.0)  # 0.099 / 0.033
    assert ratio_with < ratio_without
    # Ordering is unchanged by a constant.
    assert list(no_opex["zone_name"]) == list(with_opex["zone_name"])


def test_headroom_and_economic_status_against_a_benchmark(power: pd.DataFrame) -> None:
    ladder = merit_order.build_ladder(power, 0.0, 1.10)
    benchmark = merit_order.ComputeBenchmark(
        benchmark_id="test",
        label="test",
        usd_per_gpu_hour=1.0,
        basis="test",
        source_url="https://example.test",
    )
    framed = merit_order.add_headroom(ladder, benchmark)

    # Cheapest zone: (1.0 - 0.033) / 1.0
    assert framed.iloc[0]["headroom_pct"] == pytest.approx(0.967)
    assert bool(framed["is_economic"].all())
    # Power share of revenue at the dearest zone: 0.099 / 1.0
    assert framed.iloc[-1]["power_share_of_revenue_pct"] == pytest.approx(0.099)


def test_zones_go_uneconomic_when_price_falls_below_their_cost(
    power: pd.DataFrame,
) -> None:
    ladder = merit_order.build_ladder(power, 0.0, 1.10)
    # Price between Germany (0.066) and Italy (0.099): Italy alone is under water.
    benchmark = merit_order.ComputeBenchmark(
        benchmark_id="stress",
        label="stress",
        usd_per_gpu_hour=0.08,
        basis="test",
        source_url="https://example.test",
    )
    framed = merit_order.add_headroom(ladder, benchmark)

    uneconomic = framed[~framed["is_economic"]]
    assert list(uneconomic["zone_name"]) == ["Italy North"]
    assert framed[framed["zone_name"] == "Italy North"].iloc[0]["headroom_pct"] < 0


def test_curtailment_sequence_is_most_expensive_first(power: pd.DataFrame) -> None:
    ladder = merit_order.build_ladder(power, 0.0, 1.10)
    assert merit_order.curtailment_sequence(ladder) == [
        "Italy North",
        "Germany/Luxembourg",
        "Norway NO2",
    ]


def test_dispersion_ratio_rejects_non_positive_minimum() -> None:
    """Negative wholesale prices are real; a ratio through zero is not."""
    ladder = pd.DataFrame({"shutdown_price_usd_gpu_hour": [0.0, 0.05]})
    with pytest.raises(ValueError, match="Cannot form a dispersion ratio"):
        merit_order.dispersion_ratio(ladder, "shutdown_price_usd_gpu_hour")


def test_break_even_power_price_inverts_shutdown_price() -> None:
    """The break-even price must reproduce the compute price when fed back in."""
    from models.spark_spread import shutdown_price

    compute_price = 0.8168
    opex = 0.05
    kwh = merit_order.break_even_power_price_usd_kwh(compute_price, opex, 1.10)
    assert kwh == pytest.approx((0.8168 - 0.05) / 1.10)
    # Round-trip: at that power price, avoidable cost equals the compute price.
    assert shutdown_price(kwh, opex, 1.10) == pytest.approx(compute_price)


def test_break_even_is_far_above_any_real_tariff() -> None:
    """Pins the paper's sample-independence argument.

    Even at the cheapest compute price observed, the electricity price needed
    to force curtailment is multiples of the dearest zone in the sample
    (Austria, ~0.13 USD/kWh) and above any industrial tariff worldwide.
    """
    cheapest_observed_compute_price = 0.8168  # A100 spot
    kwh = merit_order.break_even_power_price_usd_kwh(cheapest_observed_compute_price, 0.05, 1.10)
    assert kwh > 0.60
    assert kwh > 4 * 0.129565  # more than 4x the dearest zone measured


def test_break_even_negative_when_opex_alone_exceeds_price() -> None:
    """No electricity price can rescue a fleet whose opex already exceeds revenue."""
    assert merit_order.break_even_power_price_usd_kwh(0.10, 0.50, 1.10) < 0
