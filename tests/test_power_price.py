"""Tests for pipelines.power_price (Energy-Charts)."""

from __future__ import annotations

import pandas as pd
import pytest

from pipelines import power_price

ZONE = power_price.Zone("DE-LU", "Germany/Luxembourg", "DE", "constrained")
SOURCE = "https://example.test/price"


def _payload(seconds: list[int], prices: list[float | None]) -> dict[str, object]:
    return {
        "license_info": "CC BY 4.0 test",
        "unix_seconds": seconds,
        "price": prices,
    }


def test_quarter_hourly_input_is_collapsed_to_hourly_means() -> None:
    """A 15-minute zone must not out-weight an hourly zone in the same average."""
    # Four quarter-hours in one hour, mean 20.
    payload = _payload([0, 900, 1800, 2700], [10.0, 20.0, 20.0, 30.0])
    df = power_price.parse_payload(payload, ZONE, SOURCE)

    assert len(df) == 1
    assert df.iloc[0]["price_eur_mwh"] == pytest.approx(20.0)
    assert df.iloc[0]["bzn"] == "DE-LU"
    assert df.iloc[0]["source_url"] == SOURCE


def test_nulls_are_dropped_not_zero_filled() -> None:
    """A missing price must never be read as a price of zero."""
    payload = _payload([0, 3600, 7200], [10.0, None, 30.0])
    df = power_price.parse_payload(payload, ZONE, SOURCE)

    assert len(df) == 2
    assert 0.0 not in list(df["price_eur_mwh"])


def test_length_mismatch_raises() -> None:
    payload = _payload([0, 3600], [10.0])
    with pytest.raises(power_price.PowerFetchError, match="timestamps but"):
        power_price.parse_payload(payload, ZONE, SOURCE)


def test_empty_series_raises_rather_than_returning_empty() -> None:
    payload = _payload([], [])
    with pytest.raises(power_price.PowerFetchError, match="empty series"):
        power_price.parse_payload(payload, ZONE, SOURCE)


def test_negative_prices_are_preserved_and_counted() -> None:
    """Negative wholesale prices are a real and important feature of these zones."""
    hourly = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime([0, 3600, 7200, 10800], unit="s", utc=True),
            "price_eur_mwh": [50.0, -10.0, -5.0, 100.0],
            "bzn": ["DE-LU"] * 4,
            "zone_name": ["Germany/Luxembourg"] * 4,
            "country": ["DE"] * 4,
            "role": ["constrained"] * 4,
            "source_url": [SOURCE] * 4,
            "license": ["CC BY 4.0 test"] * 4,
        }
    )
    stats = power_price.monthly_stats(hourly, 1.10, "https://example.test/fx")

    assert len(stats) == 1
    row = stats.iloc[0]
    assert row["negative_hours"] == 2
    assert row["mean_eur_mwh"] == pytest.approx(33.75)
    # 33.75 EUR/MWh * 1.10 USD/EUR / 1000 = 0.037125 USD/kWh
    assert row["mean_usd_kwh"] == pytest.approx(0.037125)
    assert row["fx_source_url"] == "https://example.test/fx"


def test_every_zone_in_the_study_declares_a_role() -> None:
    """Roles drive the supply-rich vs constrained comparison; none may be blank."""
    for zone in power_price.ZONES:
        assert zone.role in {"supply-rich", "constrained", "other"}, zone.bzn
        assert zone.name and zone.country
