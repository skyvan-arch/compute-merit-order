"""The central figure: the compute merit order and where it sits vs price.

Two panels, because the honest result needs both:

  (a) the marginal-cost ladder by zone, on a linear scale, which is what a
      merit-order curve looks like when capacity weights are not yet
      available; and
  (b) the same ladder against observed compute prices on a log scale,
      which is the only way to show a cost and a price that differ by two
      orders of magnitude on one axis.

Panel (b) is the paper's actual finding: the ordering is real, the gap is
enormous.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

REPO_ROOT = Path(__file__).resolve().parents[1]
MERIT_CSV = REPO_ROOT / "data" / "final" / "merit_order.csv"
OUTPUT_PATH = REPO_ROOT / "figures" / "merit_order.png"

ROLE_COLORS = {"supply-rich": "#2e7d32", "constrained": "#c62828", "other": "#616161"}


def load_merit(csv_path: Path = MERIT_CSV) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} missing. Run `python -m models.merit_order` first; "
            "this script will not plot fabricated data."
        )
    return pd.read_csv(csv_path)


def plot_merit_order(df: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> Path:
    # One representative slice for the ladder: the mid opex assumption.
    opex_values = sorted(df["opex_assumption_usd_gpu_hour"].unique())
    mid_opex = opex_values[len(opex_values) // 2]

    ladder = (
        df[df["opex_assumption_usd_gpu_hour"] == mid_opex]
        .drop_duplicates(subset=["zone_name"])
        .sort_values("shutdown_price_usd_gpu_hour")
        .reset_index(drop=True)
    )

    fig, (ax_ladder, ax_gap) = plt.subplots(1, 2, figsize=(13, 5.5))

    # --- Panel (a): the marginal cost ladder -----------------------------
    colors = [ROLE_COLORS.get(str(r), "#616161") for r in ladder["role"]]
    ax_ladder.barh(ladder["zone_name"], ladder["shutdown_price_usd_gpu_hour"], color=colors)
    ax_ladder.set_xlabel("Shutdown price (USD per GPU-hour)")
    ax_ladder.set_title(
        f"(a) Compute merit order: avoidable cost by zone\n"
        f"opex assumption = {mid_opex:.2f} USD/GPU-h",
        fontsize=10,
    )
    ax_ladder.invert_yaxis()
    ax_ladder.grid(axis="x", alpha=0.3)

    handles = [Rectangle((0, 0), 1, 1, color=color) for color in ROLE_COLORS.values()]
    ax_ladder.legend(handles, list(ROLE_COLORS), fontsize=8, title="Hub role", loc="lower right")

    # --- Panel (b): cost ladder vs observed compute prices ---------------
    for _, row in ladder.iterrows():
        ax_gap.plot(
            [row["shutdown_price_usd_gpu_hour"]],
            [row["merit_rank"]],
            "o",
            color=ROLE_COLORS.get(str(row["role"]), "#616161"),
        )

    benchmarks = df.drop_duplicates(subset=["compute_price_label"])[
        ["compute_price_label", "compute_price_usd_gpu_hour"]
    ]
    for offset, (_, bench) in enumerate(benchmarks.iterrows()):
        ax_gap.axvline(
            float(bench["compute_price_usd_gpu_hour"]),
            linestyle="--",
            color="#1f4e79",
            alpha=0.8,
        )
        ax_gap.text(
            float(bench["compute_price_usd_gpu_hour"]),
            0.5 + offset * 0.9,
            f" {bench['compute_price_label'].split(' (')[0]}",
            rotation=90,
            fontsize=7,
            va="bottom",
            color="#1f4e79",
        )

    ax_gap.set_xscale("log")
    ax_gap.set_xlabel("USD per GPU-hour (log scale)")
    ax_gap.set_ylabel("Merit rank (1 = cheapest)")
    ax_gap.set_title(
        "(b) Shutdown prices vs observed compute prices\n"
        "dashed lines = measured on-demand list prices",
        fontsize=10,
    )
    ax_gap.invert_yaxis()
    ax_gap.grid(alpha=0.3)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def main() -> None:
    df = load_merit()
    out = plot_merit_order(df)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
