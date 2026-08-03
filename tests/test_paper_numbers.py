"""Every numeric claim in the paper must match /data/final, or the build fails.

Any hard number the paper prose cites from our dataset must be preceded by a
`% CMO-CHECK: <csv> | <col>=<val>[,<col>=<val>...] | <column> | <value>` LaTeX
comment in the same .tex file, e.g.:

    % CMO-CHECK: entsoe_monthly_stats.csv | zone=DE-LU,month=2026-06 | mean_usd_kwh | 0.052
    The DE-LU mean day-ahead price in June 2026 was \\SI{0.052}{\\usd\\per\\kWh}.

This test collects every such tag across paper/*.tex, loads the referenced
CSV from data/final/, filters to the given row, and asserts the claimed
value matches the CSV within a small floating-point tolerance. A paper with
no numeric claims yet (e.g. this project's early phases, before real data
has been pulled) trivially passes with zero checks performed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = REPO_ROOT / "paper"
FINAL_DIR = REPO_ROOT / "data" / "final"

CHECK_TAG_RE = re.compile(
    r"%\s*CMO-CHECK:\s*(?P<csv>\S+)\s*\|\s*(?P<filters>\S+)\s*\|\s*(?P<column>\S+)\s*\|\s*(?P<value>\S+)"
)


def _find_check_tags() -> list[tuple[Path, str, dict[str, str], str, float]]:
    tags: list[tuple[Path, str, dict[str, str], str, float]] = []
    for tex_path in sorted(PAPER_DIR.glob("*.tex")):
        text = tex_path.read_text(encoding="utf-8")
        for match in CHECK_TAG_RE.finditer(text):
            filters = dict(pair.split("=", 1) for pair in match["filters"].split(","))
            tags.append((tex_path, match["csv"], filters, match["column"], float(match["value"])))
    return tags


def test_numeric_claims_match_data_final() -> None:
    tags = _find_check_tags()

    for tex_path, csv_name, filters, column, claimed_value in tags:
        csv_path = FINAL_DIR / csv_name
        assert csv_path.exists(), f"{tex_path.name} references missing {csv_path}"

        df = pd.read_csv(csv_path)
        mask = pd.Series(True, index=df.index)
        for key, value in filters.items():
            mask &= df[key].astype(str) == value
        matched = df[mask]

        assert len(matched) == 1, (
            f"{tex_path.name}: filter {filters} matched {len(matched)} rows "
            f"in {csv_name}, expected 1"
        )
        actual_value = float(matched.iloc[0][column])
        assert actual_value == pytest.approx(claimed_value, rel=1e-3), (
            f"{tex_path.name} claims {column}={claimed_value} for {filters}, "
            f"but {csv_name} has {actual_value}"
        )
