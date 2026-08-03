"""Generate the DE-LU monthly day-ahead price figure from data/final.

Never invents data: raises if data/final/entsoe_monthly_stats.csv does not
exist yet (i.e. the ENTSO-E pipeline has not been run with a real token).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
STATS_CSV = REPO_ROOT / "data" / "final" / "entsoe_monthly_stats.csv"
OUTPUT_PATH = REPO_ROOT / "figures" / "delu_monthly_price.png"


def load_delu_stats(csv_path: Path = STATS_CSV) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} does not exist. Run `python -m pipelines.entsoe --zone DE-LU` "
            "with ENTSOE_API_TOKEN set first; this script will not plot fabricated data."
        )
    df = pd.read_csv(csv_path)
    return df[df["zone"] == "DE-LU"].sort_values("month")


def plot_delu_monthly_price(df: pd.DataFrame, output_path: Path = OUTPUT_PATH) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(df["month"], df["mean_usd_kwh"], marker="o", label="Monthly mean", color="#1f4e79")
    ax.fill_between(
        df["month"],
        df["p10_usd_kwh"],
        df["p90_usd_kwh"],
        alpha=0.2,
        color="#1f4e79",
        label="P10-P90 band",
    )
    ax.set_ylabel("DE-LU day-ahead price (USD/kWh)")
    ax.set_xlabel("Month")
    ax.set_title("DE-LU wholesale day-ahead electricity price")
    ax.legend()
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def main() -> None:
    df = load_delu_stats()
    out = plot_delu_monthly_price(df)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
