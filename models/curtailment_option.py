"""Price the right to curtail as a strip of hourly options on the spread.

Why this module exists. Curtailment is an hourly decision: an operator
compares this settlement period's avoidable cost against this period's
revenue. Evaluating that decision against an *annual mean* power price
destroys the tail that decides it, and the tail is the whole phenomenon.
An earlier version of this analysis made exactly that error and concluded
that no zone is ever uneconomic; at native hourly resolution, several are.

The right to stop running when the spread is negative is a European call
on the spread, exercised hourly. Its intrinsic value over a sample is

    V = sum over hours of max(0, avoidable_cost_t - compute_price)

which is the loss avoided by curtailing rather than running regardless.
Annualised and expressed per GPU, this converts a null result ("headroom is
large on average") into a priced one ("the option is worth $X per GPU-year,
and here is where"). That is a claim about a distribution rather than a
mean, and it is the honest way to state how much the merit order is worth.

This is intrinsic value only, not an option *premium*: no volatility model,
no discounting, no forward curve. It is a lower bound on what the right to
curtail is worth, and is labelled as such wherever it is used.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.constants import DELIVERED_KW
from models.merit_order import ComputeBenchmark, load_compute_benchmarks
from pipelines.power_price import is_redistributable

REPO_ROOT = Path(__file__).resolve().parents[1]
HOURLY_CSV = REPO_ROOT / "data" / "interim" / "power_price" / "eu_hourly_prices.csv"
FINAL_DIR = REPO_ROOT / "data" / "final"

HOURS_PER_YEAR = 8_760


def load_hourly(csv_path: Path = HOURLY_CSV, *, publishable_only: bool = True) -> pd.DataFrame:
    """Load the hourly price series.

    `publishable_only` keeps only zones whose upstream licence permits
    redistribution. It defaults to True because anything derived from this
    frame may end up in /data/final, and the licence gate must fail closed.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} missing. Run `python -m pipelines.power_price` first; "
            "this model will not invent an hourly series."
        )
    df = pd.read_csv(csv_path, parse_dates=["timestamp_utc"])
    if publishable_only:
        df = df[df["license"].apply(is_redistributable)].copy()
    return df


def hourly_avoidable_cost(
    hourly: pd.DataFrame,
    fx_usd_per_eur: float,
    opex_usd_per_gpu_hour: float,
    delivered_kw: float = DELIVERED_KW,
) -> pd.DataFrame:
    """Attach per-hour avoidable cost per GPU-hour."""
    df = hourly.copy()
    df["usd_kwh"] = df["price_eur_mwh"] * fx_usd_per_eur / 1000.0
    df["avoidable_cost_usd_gpu_hour"] = df["usd_kwh"] * delivered_kw + opex_usd_per_gpu_hour
    return df


def option_value_by_zone(hourly_costed: pd.DataFrame, benchmark: ComputeBenchmark) -> pd.DataFrame:
    """Intrinsic value of the right to curtail, per zone, annualised per GPU."""
    df = hourly_costed.copy()
    strike = benchmark.usd_per_gpu_hour
    df["loss_if_forced_to_run"] = (df["avoidable_cost_usd_gpu_hour"] - strike).clip(lower=0.0)
    df["is_uneconomic_hour"] = df["avoidable_cost_usd_gpu_hour"] > strike

    grouped = df.groupby(["bzn", "zone_name", "country", "role"])
    out = grouped.agg(
        hours_observed=("avoidable_cost_usd_gpu_hour", "count"),
        hours_uneconomic=("is_uneconomic_hour", "sum"),
        intrinsic_value_usd_per_gpu_sample=("loss_if_forced_to_run", "sum"),
        max_hourly_avoidable_cost=("avoidable_cost_usd_gpu_hour", "max"),
        mean_hourly_avoidable_cost=("avoidable_cost_usd_gpu_hour", "mean"),
    ).reset_index()

    # Annualise by scaling the sample window up to a full year. Stated
    # explicitly rather than hidden: the sample is a partial year, and this
    # assumes the observed hours are representative of the ones not sampled.
    scale = HOURS_PER_YEAR / out["hours_observed"]
    out["option_value_usd_per_gpu_year"] = out["intrinsic_value_usd_per_gpu_sample"] * scale
    out["uneconomic_hours_per_year"] = out["hours_uneconomic"] * scale
    out["uneconomic_hour_share"] = out["hours_uneconomic"] / out["hours_observed"]

    out["benchmark_id"] = benchmark.benchmark_id
    out["compute_price_label"] = benchmark.label
    out["compute_price_usd_gpu_hour"] = strike
    return out


def build_all(
    fx_usd_per_eur: float,
    opex_values: list[float],
    delivered_kw: float = DELIVERED_KW,
) -> pd.DataFrame:
    """Option value across every zone, benchmark and opex assumption."""
    hourly = load_hourly()
    benchmarks = load_compute_benchmarks()

    frames: list[pd.DataFrame] = []
    for opex in opex_values:
        costed = hourly_avoidable_cost(hourly, fx_usd_per_eur, opex, delivered_kw)
        for benchmark in benchmarks:
            frame = option_value_by_zone(costed, benchmark)
            frame["opex_assumption_usd_gpu_hour"] = opex
            frame["delivered_kw"] = delivered_kw
            frames.append(frame)

    result = pd.concat(frames, ignore_index=True)
    return result.sort_values(
        ["benchmark_id", "opex_assumption_usd_gpu_hour", "option_value_usd_per_gpu_year"],
        ascending=[True, True, False],
    ).reset_index(drop=True)


def write_outputs(df: pd.DataFrame) -> Path:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FINAL_DIR / "curtailment_option_value.csv"
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fx-usd-per-eur", type=float, required=True)
    args = parser.parse_args()

    df = build_all(args.fx_usd_per_eur, [0.00, 0.05, 0.20])
    print(f"Wrote {write_outputs(df)}")


if __name__ == "__main__":
    main()
