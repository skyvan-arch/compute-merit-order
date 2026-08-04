"""Which constraint binds first, hub by hub.

The project began by asking where power is cheapest. On its own evidence
that is close to the least important question: electricity is 1-16% of GPU
rental revenue and the entire right to curtail is worth about a dollar per
GPU-year. This module asks the question that survives instead -- for a
frontier-scale cluster, which constraint actually binds, and where?

Five constraints are tested, each as an explicit physical or financial
threshold rather than a weighted score. No composite index is produced,
deliberately: weighting incommensurable constraints into a single number
manufactures precision the inputs cannot support, and hides which constraint
is doing the work. A hub is described by WHICH tests it fails.

  ABSORPTION  a 1 GW cluster exceeds ABSORPTION_LIMIT of national annual
              electricity consumption. This is the hardest constraint in the
              data: at 25% (Ireland) or 15% (Singapore) a single frontier
              cluster is a national energy policy question, not a siting
              decision, which is why such jurisdictions have moratoria.
  FIRMNESS    less than FIRM_LIMIT of generation is dispatchable. A 24/7
              load cannot be served by a grid whose surplus is variable,
              regardless of that grid's average price.
  HEADROOM    installed capacity less peak load is under HEADROOM_LIMIT_GW.
              A coarse proxy for physical room, and an optimistic one: it
              counts nameplate capacity, so a wind-heavy grid looks roomier
              than it is.
  IMPORT      the hub is a net electricity importer, so its prices are
              partly borrowed from neighbours and new load competes with
              existing demand for interconnector capacity.
  PRICE       mean wholesale price in the most expensive third of the
              sample. Listed last and weighted least on purpose: this is the
              constraint the project set out to study and the one the
              evidence demoted.

Thresholds are stated as named constants so a reader can disagree with a
number rather than with a verdict.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = REPO_ROOT / "data" / "final"

GRID_CSV = FINAL_DIR / "grid_structure.csv"
MACRO_CSV = FINAL_DIR / "macro_capacity.csv"
POWER_CSV = FINAL_DIR / "power_price_by_zone.csv"

#: A 1 GW cluster consuming more than this share of national annual
#: electricity makes the project a matter of national energy policy.
ABSORPTION_LIMIT = 0.10
#: Below this share of dispatchable generation, a 24/7 load is exposed.
FIRM_LIMIT = 0.50
#: Installed capacity minus peak load, below which there is little room.
HEADROOM_LIMIT_GW = 10.0

#: ISO2 codes for hubs, to join Energy-Charts country codes to World Bank.
HUB_ISO2: dict[str, str] = {
    "fr": "FR",
    "de": "DE",
    "nl": "NL",
    "be": "BE",
    "at": "AT",
    "no": "NO",
    "se": "SE",
    "es": "ES",
    "pt": "PT",
    "fi": "FI",
    "it": "IT",
    "pl": "PL",
    "ch": "CH",
    "ie": "IE",
    "dk": "DK",
}


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for path in (GRID_CSV, MACRO_CSV):
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing. Run the pipelines first; this model will not "
                "invent hub characteristics."
            )
    power = pd.read_csv(POWER_CSV) if POWER_CSV.exists() else pd.DataFrame()
    return pd.read_csv(GRID_CSV), pd.read_csv(MACRO_CSV), power


def build() -> pd.DataFrame:
    """Join grid, macro and price data and evaluate each constraint."""
    grid, macro, power = load_inputs()

    grid = grid.copy()
    grid["iso2"] = grid["hub_code"].map(HUB_ISO2)
    macro_cols = [
        "iso2",
        "country",
        "gdp_usd",
        "gdp_per_capita_usd",
        "one_gw_cluster_share_of_consumption",
        "electricity_use_kwh_per_capita",
    ]
    df = grid.merge(macro[[c for c in macro_cols if c in macro]], on="iso2", how="left")

    if not power.empty:
        df = df.merge(
            power[["bzn", "mean_usd_kwh", "negative_hours", "hour_count"]],
            on="bzn",
            how="left",
        )
    else:
        df["mean_usd_kwh"] = pd.NA

    # --- constraint tests -------------------------------------------------
    df["fails_absorption"] = df["one_gw_cluster_share_of_consumption"] > ABSORPTION_LIMIT
    df["fails_firmness"] = df["firm_share_of_generation"] < FIRM_LIMIT
    df["fails_headroom"] = df["capacity_headroom_gw"] < HEADROOM_LIMIT_GW
    df["fails_import"] = ~df["is_net_exporter"].astype(bool)

    if df["mean_usd_kwh"].notna().any():
        price_cut = df["mean_usd_kwh"].quantile(2 / 3)
        df["fails_price"] = df["mean_usd_kwh"] > price_cut
    else:
        df["fails_price"] = False

    test_cols = [
        "fails_absorption",
        "fails_firmness",
        "fails_headroom",
        "fails_import",
        "fails_price",
    ]
    df[test_cols] = df[test_cols].fillna(False).astype(bool)
    df["constraints_failed"] = df[test_cols].sum(axis=1)

    # Which constraint binds FIRST, in order of how hard it is to relieve.
    # Absorption and firmness are structural: they take a decade and a
    # national programme to change. Price is the softest -- it can move in a
    # season -- which is precisely why it is the least interesting.
    order = [
        ("fails_absorption", "ABSORPTION"),
        ("fails_firmness", "FIRMNESS"),
        ("fails_headroom", "HEADROOM"),
        ("fails_import", "IMPORT"),
        ("fails_price", "PRICE"),
    ]

    def binding(row: pd.Series) -> str:
        for col, label in order:
            if bool(row[col]):
                return label
        return "NONE"

    df["binding_constraint"] = df.apply(binding, axis=1)

    # How many 1 GW clusters before the absorption limit is reached.
    df["clusters_gw_to_absorption_limit"] = (
        ABSORPTION_LIMIT / df["one_gw_cluster_share_of_consumption"]
    )

    return df.sort_values(
        ["constraints_failed", "one_gw_cluster_share_of_consumption"]
    ).reset_index(drop=True)


def write_outputs(df: pd.DataFrame) -> Path:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FINAL_DIR / "hub_scorecard.csv"
    df.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    df = build()
    print(f"Wrote {write_outputs(df)} ({len(df)} hubs)")


if __name__ == "__main__":
    main()
