"""Tests for the compute spark spread model.

All inputs here are hand-chosen test values, not market data.
"""

from __future__ import annotations

import pytest

from config import constants
from models import spark_spread


def test_delivered_kw_default_matches_documented_derivation() -> None:
    # (0.700 TDP + 0.180 overhead) * 1.25 PUE = 1.100 kW.
    # Only the literal is asserted. Re-asserting the defining expression
    # would be a tautology -- DELIVERED_KW *is* that expression -- and would
    # silently "pass" if every input changed together.
    assert constants.DELIVERED_KW == pytest.approx(1.10)


def test_delivered_kw_default_sits_inside_its_sensitivity_range() -> None:
    assert (
        constants.DELIVERED_KW_SENSITIVITY_MIN
        <= constants.DELIVERED_KW
        <= constants.DELIVERED_KW_SENSITIVITY_MAX
    )


def test_no_default_opex_point_estimate_exists() -> None:
    """The brief forbids inventing an opex point estimate — guard against drift."""
    assert constants.MARGINAL_OPEX_USD_PER_GPU_HOUR is None


def test_power_cost_per_gpu_hour() -> None:
    # 0.05 USD/kWh * 1.10 kW = 0.055 USD per GPU-hour
    assert spark_spread.power_cost_per_gpu_hour(0.05) == pytest.approx(0.055)
    assert spark_spread.power_cost_per_gpu_hour(0.05, delivered_kw=1.40) == pytest.approx(0.07)


def test_power_cost_rejects_negative_delivered_kw() -> None:
    with pytest.raises(ValueError, match="delivered_kw must be non-negative"):
        spark_spread.power_cost_per_gpu_hour(0.05, delivered_kw=-0.1)


def test_usd_per_kwh_from_usd_per_mwh() -> None:
    assert spark_spread.usd_per_kwh_from_usd_per_mwh(50.0) == pytest.approx(0.05)


def test_shutdown_price_adds_opex_to_power_cost() -> None:
    # 0.055 power + 0.02 opex = 0.075
    assert spark_spread.shutdown_price(0.05, 0.02) == pytest.approx(0.075)


def test_shutdown_price_requires_explicit_opex() -> None:
    """Opex is positional and mandatory — no accidental zero default."""
    with pytest.raises(TypeError):
        spark_spread.shutdown_price(0.05)  # type: ignore[call-arg]


def test_shutdown_price_rejects_negative_opex() -> None:
    with pytest.raises(ValueError, match="marginal_opex_usd_per_gpu_hour"):
        spark_spread.shutdown_price(0.05, -0.01)


def test_headroom_positive_negative_and_breakeven() -> None:
    # price 0.10, cost 0.075 -> 25% headroom
    assert spark_spread.headroom(0.10, 0.075) == pytest.approx(0.25)
    # at breakeven headroom is exactly zero
    assert spark_spread.headroom(0.10, 0.10) == pytest.approx(0.0)
    # below shutdown price headroom goes negative
    assert spark_spread.headroom(0.10, 0.125) == pytest.approx(-0.25)


def test_headroom_rejects_non_positive_compute_price() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        spark_spread.headroom(0.0, 0.05)


def test_is_economic_boundary() -> None:
    assert spark_spread.is_economic(0.10, 0.075)
    assert spark_spread.is_economic(0.10, 0.10)  # exactly at shutdown price
    assert not spark_spread.is_economic(0.10, 0.11)


def test_sweep_covers_the_full_grid() -> None:
    points = spark_spread.sweep(
        price_usd_kwh=0.05,
        delivered_kw_values=[0.9, 1.1, 1.4],
        marginal_opex_values=[0.01, 0.02],
        compute_price_usd_gpu_hour=0.10,
    )
    assert len(points) == 6
    assert all(p.headroom_pct is not None for p in points)

    # Cheapest corner: lowest kW and lowest opex.
    cheapest = min(points, key=lambda p: p.shutdown_price_usd_gpu_hour)
    assert cheapest.delivered_kw == 0.9
    assert cheapest.marginal_opex_usd_per_gpu_hour == 0.01
    assert cheapest.shutdown_price_usd_gpu_hour == pytest.approx(0.05 * 0.9 + 0.01)


def test_headroom_at_realistic_market_prices_is_extreme() -> None:
    """Pin the paper's central finding at real observed magnitudes.

    Every other example here uses toy values of the same order as the power
    cost, which is exactly the implicit assumption the data falsifies. This
    test uses measured figures: DE-LU at ~0.1138 USD/kWh against H100
    on-demand list (~14.13) and 5-year reserved (~5.65) USD/GPU-hour.
    """
    power_usd_kwh = 0.1138
    cost = spark_spread.shutdown_price(power_usd_kwh, 0.0, constants.DELIVERED_KW)
    assert cost == pytest.approx(0.1252, abs=1e-3)

    # Power is ~0.9% of on-demand revenue, ~2.2% of 5-year reserved revenue.
    assert spark_spread.headroom(14.1335, cost) > 0.99
    assert spark_spread.headroom(5.6534, cost) > 0.97
    # Even the cheapest observed compute price leaves the fleet far above cost.
    assert spark_spread.is_economic(0.8168, cost)


def test_sweep_without_compute_price_leaves_headroom_undefined() -> None:
    points = spark_spread.sweep(
        price_usd_kwh=0.05,
        delivered_kw_values=[1.1],
        marginal_opex_values=[0.02],
    )
    assert len(points) == 1
    assert points[0].headroom_pct is None
