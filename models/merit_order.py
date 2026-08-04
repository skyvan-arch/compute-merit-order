"""Build the compute merit order and test the paper's central claims.

Joins the power-cost surface (data/final/power_price_by_zone.csv) to the
compute-price series (data/final/compute_price_by_model.csv) and produces:

  * a marginal-cost ladder — zones sorted ascending by shutdown price;
  * headroom against each observed compute-price benchmark;
  * the dispersion ratio, which is the paper's "~3x" claim made testable;
  * the power share of revenue, which is what decides whether the
    spark-spread analogy is economically meaningful at all.

On what the shutdown price includes. For a fleet whose accelerators are
already bought, capital cost is sunk and therefore irrelevant to the
decision to keep running: the operator curtails when revenue falls below
*avoidable* cost, which is power plus non-power marginal opex. That is the
quantity modelled here, and it is the correct one for a shutdown question.
It is emphatically NOT the right quantity for an investment question — a
fleet can be far above its shutdown price while being a loss-making
investment — and this module makes no claim about the latter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config.constants import DELIVERED_KW
from models.spark_spread import headroom, shutdown_price

REPO_ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = REPO_ROOT / "data" / "final"
POWER_CSV = FINAL_DIR / "power_price_by_zone.csv"
COMPUTE_CSV = FINAL_DIR / "compute_price_by_model.csv"


@dataclass(frozen=True)
class ComputeBenchmark:
    """One compute-price level to evaluate the merit order against."""

    benchmark_id: str
    """Comma-free, space-free identifier. The paper's CMO-CHECK tags filter on
    this, and that filter syntax is comma-delimited, so the human-readable
    `label` (which contains commas) cannot be used as a key."""
    label: str
    usd_per_gpu_hour: float
    basis: str
    source_url: str


def load_power_costs(csv_path: Path = POWER_CSV) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} missing. Run `python -m pipelines.power_price` first; "
            "this model will not invent a power cost."
        )
    return pd.read_csv(csv_path)


def load_compute_benchmarks(csv_path: Path = COMPUTE_CSV) -> list[ComputeBenchmark]:
    """Derive compute-price benchmarks from the observed data, not from memory."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} missing. Run `python -m pipelines.compute_price` first."
        )
    df = pd.read_csv(csv_path)
    benchmarks: list[ComputeBenchmark] = []
    for _, row in df.iterrows():
        model_slug = str(row["accelerator_model"]).replace("NVIDIA ", "").strip().lower()
        price_type = str(row["price_type"])
        benchmarks.append(
            ComputeBenchmark(
                benchmark_id=f"{model_slug}_{price_type}",
                label=f"{row['accelerator_model']} ({price_type.replace('_', ' ')})",
                usd_per_gpu_hour=float(row["mean_usd_per_gpu_hour"]),
                basis=str(row["price_basis"]),
                source_url=str(row["price_source_url"]),
            )
        )
    return benchmarks


def build_ladder(
    power: pd.DataFrame,
    opex_usd_per_gpu_hour: float,
    delivered_kw: float = DELIVERED_KW,
) -> pd.DataFrame:
    """Zones sorted ascending by avoidable cost per GPU-hour."""
    df = power.copy()
    df["delivered_kw"] = delivered_kw
    df["marginal_opex_usd_per_gpu_hour"] = opex_usd_per_gpu_hour
    df["power_cost_usd_gpu_hour"] = df["mean_usd_kwh"] * delivered_kw
    df["shutdown_price_usd_gpu_hour"] = [
        shutdown_price(price, opex_usd_per_gpu_hour, delivered_kw) for price in df["mean_usd_kwh"]
    ]
    df = df.sort_values("shutdown_price_usd_gpu_hour").reset_index(drop=True)
    df["merit_rank"] = df.index + 1
    return df


def add_headroom(ladder: pd.DataFrame, benchmark: ComputeBenchmark) -> pd.DataFrame:
    """Attach headroom and economic status against one compute-price level."""
    df = ladder.copy()
    df["benchmark_id"] = benchmark.benchmark_id
    df["compute_price_label"] = benchmark.label
    df["compute_price_usd_gpu_hour"] = benchmark.usd_per_gpu_hour
    df["headroom_pct"] = [
        headroom(benchmark.usd_per_gpu_hour, cost) for cost in df["shutdown_price_usd_gpu_hour"]
    ]
    df["is_economic"] = df["shutdown_price_usd_gpu_hour"] <= benchmark.usd_per_gpu_hour
    df["power_share_of_revenue_pct"] = df["power_cost_usd_gpu_hour"] / benchmark.usd_per_gpu_hour
    return df


def dispersion_ratio(ladder: pd.DataFrame, column: str) -> float:
    """Max/min ratio across zones — the paper's '~3x' claim, made testable."""
    values = ladder[column]
    minimum = float(values.min())
    if minimum <= 0:
        raise ValueError(f"Cannot form a dispersion ratio: min({column}) = {minimum} <= 0")
    return float(values.max()) / minimum


def break_even_power_price_usd_kwh(
    compute_price_usd_gpu_hour: float,
    marginal_opex_usd_per_gpu_hour: float,
    delivered_kw: float = DELIVERED_KW,
) -> float:
    """Electricity price at which a fleet is exactly at its shutdown price.

    Inverts shutdown_price(): the price per kWh that would make avoidable cost
    equal the given compute price.

    This is what makes the paper's negative result robust to its own narrow
    sample. Rather than arguing about whether a wider set of zones would
    change the answer, it states the power price a zone would need in order
    to be curtailed at all, which any reader can compare against the dearest
    electricity they know of. Returns a negative number when opex alone
    already exceeds the compute price, meaning no electricity price can save
    the fleet.
    """
    return (compute_price_usd_gpu_hour - marginal_opex_usd_per_gpu_hour) / delivered_kw


def break_even_table(
    benchmarks: list[ComputeBenchmark],
    opex_values: list[float],
    delivered_kw: float = DELIVERED_KW,
) -> pd.DataFrame:
    """Break-even power price for every benchmark x opex combination."""
    rows: list[dict[str, object]] = []
    for benchmark in benchmarks:
        for opex in opex_values:
            rows.append(
                {
                    "benchmark_id": benchmark.benchmark_id,
                    "compute_price_label": benchmark.label,
                    "compute_price_usd_gpu_hour": benchmark.usd_per_gpu_hour,
                    "opex_assumption_usd_gpu_hour": opex,
                    "delivered_kw": delivered_kw,
                    "break_even_power_usd_kwh": break_even_power_price_usd_kwh(
                        benchmark.usd_per_gpu_hour, opex, delivered_kw
                    ),
                }
            )
    return pd.DataFrame(rows)


def curtailment_sequence(ladder: pd.DataFrame) -> list[str]:
    """Zone names in the order they go uneconomic as compute prices fall.

    Descending avoidable cost: the most expensive zone curtails first.

    Named curtailment, not retirement, deliberately. This ladder is built
    from avoidable cost, which governs the short-run decision to stop
    *running*. Retirement is a long-run decision governed by going-forward
    fixed costs and expected revenue — which is why mothballed plants exist
    above their spark spread. Calling this a retirement order would be a
    category error, and for GPUs the retirement decision is dominated by
    silicon vintage and capital recovery, not by geography.
    """
    ordered = ladder.sort_values("shutdown_price_usd_gpu_hour", ascending=False)
    return [str(name) for name in ordered["zone_name"]]


def build_all(
    opex_values: list[float], delivered_kw: float = DELIVERED_KW
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Full merit-order table across the opex sweep and every benchmark.

    Returns (detailed rows, summary of the claims under test).
    """
    power = load_power_costs()
    benchmarks = load_compute_benchmarks()

    rows: list[pd.DataFrame] = []
    for opex in opex_values:
        ladder = build_ladder(power, opex, delivered_kw)
        for benchmark in benchmarks:
            frame = add_headroom(ladder, benchmark)
            frame["opex_assumption_usd_gpu_hour"] = opex
            rows.append(frame)

    detail = pd.concat(rows, ignore_index=True)

    summary_rows: list[dict[str, object]] = []
    for opex in opex_values:
        ladder = build_ladder(power, opex, delivered_kw)
        for benchmark in benchmarks:
            frame = add_headroom(ladder, benchmark)
            summary_rows.append(
                {
                    "opex_assumption_usd_gpu_hour": opex,
                    "benchmark_id": benchmark.benchmark_id,
                    "compute_price_label": benchmark.label,
                    "compute_price_usd_gpu_hour": benchmark.usd_per_gpu_hour,
                    "cheapest_zone": frame.iloc[0]["zone_name"],
                    "cheapest_shutdown_usd_gpu_hour": frame.iloc[0]["shutdown_price_usd_gpu_hour"],
                    "dearest_zone": frame.iloc[-1]["zone_name"],
                    "dearest_shutdown_usd_gpu_hour": frame.iloc[-1]["shutdown_price_usd_gpu_hour"],
                    "shutdown_dispersion_ratio": dispersion_ratio(
                        frame, "shutdown_price_usd_gpu_hour"
                    ),
                    "power_cost_dispersion_ratio": dispersion_ratio(
                        frame, "power_cost_usd_gpu_hour"
                    ),
                    "min_headroom_pct": float(frame["headroom_pct"].min()),
                    "max_headroom_pct": float(frame["headroom_pct"].max()),
                    "zones_uneconomic": int((~frame["is_economic"]).sum()),
                    "zones_total": len(frame),
                    "max_power_share_of_revenue_pct": float(
                        frame["power_share_of_revenue_pct"].max()
                    ),
                    "price_fall_to_first_curtailment_pct": 1.0
                    - float(frame["shutdown_price_usd_gpu_hour"].max())
                    / benchmark.usd_per_gpu_hour,
                }
            )

    return detail, pd.DataFrame(summary_rows)


def write_outputs(
    detail: pd.DataFrame, summary: pd.DataFrame, break_even: pd.DataFrame
) -> list[Path]:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = FINAL_DIR / "merit_order.csv"
    summary_path = FINAL_DIR / "merit_order_summary.csv"
    break_even_path = FINAL_DIR / "break_even_power_price.csv"
    detail.to_csv(detail_path, index=False)
    summary.to_csv(summary_path, index=False)
    break_even.to_csv(break_even_path, index=False)
    return [detail_path, summary_path, break_even_path]


def main() -> None:
    # Opex sweep bounds, not estimates — no public source exists (issue #14).
    opex_values = [0.00, 0.05, 0.20]
    detail, summary = build_all(opex_values)
    break_even = break_even_table(load_compute_benchmarks(), opex_values)
    for path in write_outputs(detail, summary, break_even):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
