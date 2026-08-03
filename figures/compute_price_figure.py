"""Plot published GPU list prices per GPU-hour, by accelerator and price type.

Reads data/final/compute_price_observations.csv. Raises rather than plotting
anything if that file is absent.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVATIONS_CSV = REPO_ROOT / "data" / "final" / "compute_price_observations.csv"
OUTPUT_PATH = REPO_ROOT / "figures" / "compute_price_per_gpu_hour.png"


def load_observations(csv_path: Path = OBSERVATIONS_CSV) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} does not exist. Run `python -m pipelines.compute_price` first; "
            "this script will not plot fabricated data."
        )
    return pd.read_csv(csv_path)


def plot_compute_prices(df: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> Path:
    models = sorted(df["accelerator_model"].unique())
    price_types = ["on_demand", "spot"]
    colors = {"on_demand": "#1f4e79", "spot": "#c55a11"}
    labels = {"on_demand": "On-demand list", "spot": "Spot"}

    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.35

    for offset, price_type in zip([-0.5, 0.5], price_types, strict=True):
        means = []
        errors_low = []
        errors_high = []
        for model in models:
            subset = df[(df["accelerator_model"] == model) & (df["price_type"] == price_type)]
            mean = subset["usd_per_gpu_hour"].mean()
            means.append(mean)
            errors_low.append(mean - subset["usd_per_gpu_hour"].min())
            errors_high.append(subset["usd_per_gpu_hour"].max() - mean)

        positions = [i + offset * width for i in range(len(models))]
        ax.bar(
            positions,
            means,
            width=width,
            yerr=[errors_low, errors_high],
            capsize=4,
            color=colors[price_type],
            label=labels[price_type],
        )

    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models)
    ax.set_ylabel("USD per GPU-hour")
    ax.set_title(
        "Azure published GPU prices per GPU-hour\n"
        "(hyperscaler list prices; bars span regional min-max)",
        fontsize=10,
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def main() -> None:
    df = load_observations()
    out = plot_compute_prices(df)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
