"""Tests for pipelines.entsoe using a synthetic fixture — never real market data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from pipelines import entsoe

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "entsoe_delu_sample.xml"


def test_parse_day_ahead_xml_reads_fixture() -> None:
    xml_bytes = FIXTURE_PATH.read_bytes()
    prices = entsoe.parse_day_ahead_xml(
        xml_bytes, zone="DE-LU", source_url="https://example.test/fixture"
    )

    assert len(prices) == 4
    assert [p.price_eur_mwh for p in prices] == [45.32, -3.10, 50.00, 62.75]
    assert prices[0].timestamp_utc == datetime(2025, 12, 31, 23, 0, tzinfo=UTC)
    assert prices[-1].timestamp_utc == datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    assert all(p.zone == "DE-LU" for p in prices)
    assert all(p.source_url == "https://example.test/fixture" for p in prices)


def test_parse_day_ahead_xml_rejects_non_hourly_resolution() -> None:
    xml_bytes = FIXTURE_PATH.read_bytes().replace(b"PT60M", b"PT15M")
    with pytest.raises(ValueError, match="Unsupported resolution"):
        entsoe.parse_day_ahead_xml(
            xml_bytes, zone="DE-LU", source_url="https://example.test/fixture"
        )


def test_compute_monthly_stats_matches_hand_calculation() -> None:
    # Four synthetic hours, all in the same month, one negative-price hour.
    hourly = pd.DataFrame(
        {
            "timestamp_utc": [
                datetime(2026, 1, 1, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 1, 2, tzinfo=UTC),
                datetime(2026, 1, 1, 3, tzinfo=UTC),
            ],
            "zone": ["DE-LU"] * 4,
            "price_eur_mwh": [45.32, -3.10, 50.00, 62.75],
            "source_url": ["https://example.test/fixture"] * 4,
            "as_of_date": ["2026-01-02"] * 4,
        }
    )
    fx = pd.DataFrame({"month": ["2026-01"], "usd_per_eur": [1.10]})

    stats = entsoe.compute_monthly_stats(hourly, fx)

    assert len(stats) == 1
    row = stats.iloc[0]
    expected_mean = hourly["price_eur_mwh"].mean()
    assert row["mean_eur_mwh"] == pytest.approx(expected_mean)
    assert row["negative_hours"] == 1
    assert row["mean_usd_kwh"] == pytest.approx(expected_mean * 1.10 / 1000.0)
    assert row["source_url"] == "https://example.test/fixture"
    assert row["as_of_date"] == "2026-01-02"


def test_run_without_token_raises_and_does_not_fabricate_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    with pytest.raises(entsoe.MissingTokenError):
        entsoe.run("DE-LU", months=1)
