"""The compute spark spread: power cost, shutdown price, and headroom.

Formal definitions follow paper/main.tex Section 3. Every function here is
pure and takes its economic inputs explicitly — in particular non-power
marginal opex, which this project refuses to assign a default point estimate
(see config/constants.py and GitHub issue #14).

Terminology note: in this model the *shutdown price* and the *marginal cost*
per GPU-hour are the same quantity — the variable cost of running one
accelerator for one hour, below which a rational operator curtails. The
hubs.geojson schema (Phase 4) carries both `est_marginal_cost_usd_gpu_hr`
and `shutdown_price_usd_gpu_hr` as separate fields; they are populated from
the same calculation unless and until a hub is found where they genuinely
diverge, in which case that divergence must be documented per hub.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from config.constants import DELIVERED_KW, KWH_PER_MWH


def usd_per_kwh_from_usd_per_mwh(price_usd_mwh: float) -> float:
    """Convert a wholesale USD/MWh price to USD/kWh."""
    return price_usd_mwh / KWH_PER_MWH


def power_cost_per_gpu_hour(price_usd_kwh: float, delivered_kw: float = DELIVERED_KW) -> float:
    """Electricity cost of running one accelerator for one hour.

    Args:
        price_usd_kwh: delivered electricity price in USD per kWh.
        delivered_kw: grid draw per accelerator-hour including PUE. Defaults
            to the project's single named constant.
    """
    if delivered_kw < 0:
        raise ValueError(f"delivered_kw must be non-negative, got {delivered_kw}")
    return price_usd_kwh * delivered_kw


def shutdown_price(
    price_usd_kwh: float,
    marginal_opex_usd_per_gpu_hour: float,
    delivered_kw: float = DELIVERED_KW,
) -> float:
    """Compute price below which the fleet is uneconomic to run.

    `marginal_opex_usd_per_gpu_hour` is required and has no default by
    design: the project brief forbids inventing a point estimate for it.
    """
    if marginal_opex_usd_per_gpu_hour < 0:
        raise ValueError(
            "marginal_opex_usd_per_gpu_hour must be non-negative, "
            f"got {marginal_opex_usd_per_gpu_hour}"
        )
    return power_cost_per_gpu_hour(price_usd_kwh, delivered_kw) + marginal_opex_usd_per_gpu_hour


def headroom(compute_price_usd_gpu_hour: float, marginal_cost_usd_gpu_hour: float) -> float:
    """Fractional margin over marginal cost: (price - cost) / price.

    Negative headroom means the fleet is below its shutdown price. Raises on
    a non-positive compute price rather than returning an infinity, because
    a zero or negative compute price is a data error, not an economic state
    this model is defined over.
    """
    if compute_price_usd_gpu_hour <= 0:
        raise ValueError(
            f"compute_price_usd_gpu_hour must be positive, got {compute_price_usd_gpu_hour}"
        )
    return (compute_price_usd_gpu_hour - marginal_cost_usd_gpu_hour) / compute_price_usd_gpu_hour


def is_economic(compute_price_usd_gpu_hour: float, marginal_cost_usd_gpu_hour: float) -> bool:
    """True when the compute price at least covers marginal cost."""
    return compute_price_usd_gpu_hour >= marginal_cost_usd_gpu_hour


@dataclass(frozen=True)
class SensitivityPoint:
    """One cell of a sensitivity sweep."""

    delivered_kw: float
    marginal_opex_usd_per_gpu_hour: float
    shutdown_price_usd_gpu_hour: float
    headroom_pct: float | None
    """None when no compute price was supplied to evaluate headroom against."""


def sweep(
    price_usd_kwh: float,
    delivered_kw_values: Iterable[float],
    marginal_opex_values: Iterable[float],
    compute_price_usd_gpu_hour: float | None = None,
) -> list[SensitivityPoint]:
    """Evaluate the shutdown price across a grid of assumptions.

    Both sweep axes are supplied by the caller. There is deliberately no
    default opex grid: see config.constants.MARGINAL_OPEX_USD_PER_GPU_HOUR.
    """
    delivered_kw_list: Sequence[float] = list(delivered_kw_values)
    opex_list: Sequence[float] = list(marginal_opex_values)

    points: list[SensitivityPoint] = []
    for kw in delivered_kw_list:
        for opex in opex_list:
            cost = shutdown_price(price_usd_kwh, opex, kw)
            points.append(
                SensitivityPoint(
                    delivered_kw=kw,
                    marginal_opex_usd_per_gpu_hour=opex,
                    shutdown_price_usd_gpu_hour=cost,
                    headroom_pct=(
                        headroom(compute_price_usd_gpu_hour, cost)
                        if compute_price_usd_gpu_hour is not None
                        else None
                    ),
                )
            )
    return points
