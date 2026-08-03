"""Compare working-tree data/final CSVs against HEAD and flag material changes.

Used by .github/workflows/refresh.yml: after a pipeline re-run, this
determines whether any numeric column changed by more than --threshold
(relative), so the workflow only opens a PR when something material moved.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = REPO_ROOT / "data" / "final"


def _read_head_version(path: Path) -> pd.DataFrame | None:
    rel = path.relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    from io import StringIO

    return pd.read_csv(StringIO(result.stdout))


def max_relative_change(old: pd.DataFrame, new: pd.DataFrame) -> float:
    numeric_cols = [c for c in new.columns if pd.api.types.is_numeric_dtype(new[c])]
    common_cols = [c for c in numeric_cols if c in old.columns]
    if not common_cols:
        return 0.0

    n = min(len(old), len(new))
    if n == 0:
        return 0.0

    old_vals = old[common_cols].iloc[:n]
    new_vals = new[common_cols].iloc[:n]
    denom = old_vals.abs().clip(lower=1e-9)
    relative_change = ((new_vals - old_vals).abs() / denom).to_numpy()
    return float(relative_change.max()) if relative_change.size else 0.0


def check_all(threshold: float) -> tuple[bool, str]:
    changed_files: list[str] = []
    for path in sorted(FINAL_DIR.glob("*.csv")):
        old = _read_head_version(path)
        if old is None:
            changed_files.append(f"{path.name} (new file)")
            continue
        new = pd.read_csv(path)
        change = max_relative_change(old, new)
        if change > threshold:
            changed_files.append(f"{path.name} (max change {change:.1%})")

    changed = bool(changed_files)
    summary = (
        "Material changes detected:\n" + "\n".join(f"- {f}" for f in changed_files)
        if changed
        else "No material changes."
    )
    return changed, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.02)
    args = parser.parse_args()

    changed, summary = check_all(args.threshold)
    print(summary)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
            f.write(f"summary<<EOF\n{summary}\nEOF\n")


if __name__ == "__main__":
    main()
