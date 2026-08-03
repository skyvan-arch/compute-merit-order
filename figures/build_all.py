"""Regenerate every figure from data/final.

Runs each figure generator in turn. A generator whose required input data
is not yet available (e.g. a pipeline that hasn't been run with a real API
token yet) is skipped with a warning rather than failing the build — as
more sources come online in later phases, this keeps CI green without ever
faking the missing figure.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from figures import entsoe_price_figure

GENERATORS: list[tuple[str, Callable[[], object]]] = [
    ("entsoe_price_figure", entsoe_price_figure.main),
]


def main() -> None:
    skipped: list[str] = []
    for name, generator in GENERATORS:
        try:
            generator()
        except FileNotFoundError as exc:
            print(f"[skip] {name}: {exc}", file=sys.stderr)
            skipped.append(name)

    if skipped:
        print(f"Skipped {len(skipped)} figure(s) pending data: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
