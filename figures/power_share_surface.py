"""The core exhibit: power's share of revenue against the compute price.

The single number "power is 1% of revenue" is true only for the newest
silicon at list price in a cheap zone. Across the nine revenue bases we
measure, power's share spans 0.61% to 16.5% — a factor of 27 — and it moves
monotonically with the compute price, not with geography.

That is the point of this chart. The x-axis is the compute price; the band
is the spread across our seven European zones. The vertical spread at any
given price (geography) is small; the horizontal movement (price basis, and
therefore silicon vintage and contract type) is enormous. Anyone reading a
single headline percentage is reading one point on a steep curve.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
MERIT_CSV = REPO_ROOT / "data" / "final" / "merit_order.csv"
OUTPUT_PATH = REPO_ROOT / "figures" / "power_share_surface.png"


def load(csv_path: Path = MERIT_CSV) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} missing. Run `python -m models.merit_order` first; "
            "this script will not plot fabricated data."
        )
    return pd.read_csv(csv_path)


def plot_surface(df: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> Path:
    # Power cost only (opex excluded) so the chart shows the electricity share.
    d = df[df["opex_assumption_usd_gpu_hour"] == 0.0]

    cheapest = d.loc[d.groupby("benchmark_id")["power_cost_usd_gpu_hour"].idxmin()]
    dearest = d.loc[d.groupby("benchmark_id")["power_cost_usd_gpu_hour"].idxmax()]
    merged = cheapest.merge(dearest, on="benchmark_id", suffixes=("_cheap", "_dear")).sort_values(
        "compute_price_usd_gpu_hour_cheap"
    )

    x = merged["compute_price_usd_gpu_hour_cheap"].to_numpy()
    lo = merged["power_share_of_revenue_pct_cheap"].to_numpy() * 100
    hi = merged["power_share_of_revenue_pct_dear"].to_numpy() * 100

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.fill_between(x, lo, hi, alpha=0.25, color="#1f4e79", label="Range across 7 EU zones")
    ax.plot(x, hi, "o-", color="#c62828", label="Dearest zone (Austria)")
    ax.plot(x, lo, "o-", color="#2e7d32", label="Cheapest zone (France)")

    labels = {
        "h100_on_demand": "H100 list",
        "h100_reserved_5yr": "H100 5yr",
        "a100_on_demand": "A100 list",
        "h100_spot": "H100 spot",
        "a100_reserved_3yr": "A100 3yr",
        "a100_spot": "A100 spot",
    }
    for _, row in merged.iterrows():
        key = str(row["benchmark_id"])
        if key in labels:
            ax.annotate(
                labels[key],
                (
                    row["compute_price_usd_gpu_hour_cheap"],
                    row["power_share_of_revenue_pct_dear"] * 100,
                ),
                textcoords="offset points",
                xytext=(4, 6),
                fontsize=8,
            )

    ax.axhline(10, linestyle=":", color="#555", linewidth=1)
    ax.text(float(np.max(x)), 10.4, "10% of revenue", ha="right", fontsize=8, color="#555")

    ax.set_xscale("log")
    ax.set_xlabel("Compute price (USD per GPU-hour, log scale)")
    ax.set_ylabel("Electricity as % of revenue")
    ax.set_title(
        "Power is trivial for new silicon at list price, and material for old\n"
        "silicon at spot. Geography moves this far less than price basis does.",
        fontsize=11,
    )
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def main() -> None:
    out = plot_surface(load())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
