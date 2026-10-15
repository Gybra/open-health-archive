import importlib
from datetime import date

import pandas as pd
import pytest

from healthviz.settings import Settings


def module():
    assert importlib.util.find_spec("healthviz.analysis.heart"), "heart analysis is missing"
    return importlib.import_module("healthviz.analysis.heart")


def heart(values, freq="1min"):
    return pd.DataFrame(
        {
            "time_utc": pd.date_range("2026-01-01", periods=len(values), freq=freq, tz="UTC"),
            "bpm": values,
            "physical_device_id": ["fictional"] * len(values),
        }
    )


def test_max_hr_config_confirmed_peak_age_then_missing():
    mod = module()
    hr = heart([170, 180, 175, 220, 170])
    workouts = pd.DataFrame(
        {
            "start_utc": [pd.Timestamp("2026-01-01", tz="UTC")],
            "end_utc": [pd.Timestamp("2026-01-01T01:00:00Z")],
        }
    )
    assert mod.max_hr(Settings(max_hr=190), hr, workouts, date(2026, 1, 1)) == (190, "configured")
    assert mod.max_hr(Settings(), hr, workouts, date(2026, 1, 1)) == (180, "observed")
    assert mod.max_hr(Settings(birth_year=1986), hr.iloc[:0], workouts, date(2026, 1, 1)) == (
        180,
        "age_formula",
    )
    assert mod.max_hr(Settings(), hr.iloc[:0], workouts, date(2026, 1, 1)) == (None, "unavailable")
    assert mod.max_hr(Settings(), hr, workouts, date(2028, 2, 29)) == (None, "unavailable")


def test_zones_boundaries_and_two_minute_cap():
    mod = module()
    hr = heart([100, 120, 200, 220], freq="3min")
    zones = mod.zone_seconds(
        hr, pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-01-01T00:10:00Z"), 200
    ).set_index("zone")
    assert zones.loc["Z1", "seconds"] == 120
    assert zones.loc["Z2", "seconds"] == 120
    assert zones.loc["Z5", "seconds"] == 120
    assert zones.loc["above max", "seconds"] == 0
    assert mod.zone_seconds(hr, hr.time_utc.iloc[0], hr.time_utc.iloc[-1], None).empty


def test_resting_window_requires_six_samples_and_24_minutes():
    mod = module()
    hr = heart([60] * 7, freq="5min")
    sleep = pd.DataFrame(
        {
            "start_utc": [hr.time_utc.iloc[0]],
            "end_utc": [hr.time_utc.iloc[-1]],
            "date_local": [date(2026, 1, 1)],
            "main": [True],
            "eligible": [True],
            "physical_device_id": ["fictional"],
        }
    )
    resting = mod.resting_from_sleep(hr, sleep)
    assert resting.iloc[0].bpm == 60
    assert resting.iloc[0].computed_by == "app"
    missing = mod.resting_from_sleep(hr.iloc[:5], sleep).iloc[0]
    assert pd.isna(missing.bpm)
    assert pd.isna(missing.computed_by)
    assert missing.quality == "missing: fewer than six heart rate samples"


@pytest.mark.parametrize("last_minute,expected", [(23, None), (24, 60)])
def test_resting_window_support_boundary(last_minute, expected):
    hr = heart([60] * 6)
    hr["time_utc"] = pd.to_datetime(
        [f"2026-01-01T00:{m:02}:00Z" for m in [0, 5, 10, 15, 20, last_minute]]
    )
    sleep = pd.DataFrame(
        {
            "start_utc": [pd.Timestamp("2026-01-01T00:00:00Z")],
            "end_utc": [pd.Timestamp("2026-01-01T00:30:00Z")],
            "date_local": [date(2026, 1, 1)],
            "main": [True],
            "eligible": [True],
        }
    )
    row = module().resting_from_sleep(hr, sleep).iloc[0]
    if expected is None:
        assert pd.isna(row.bpm)
        assert row.quality == "missing: no supported 30-minute window"
    else:
        assert row.bpm == expected
        assert row.quality == "derived from main sleep"


def test_vendor_resting_wins_and_sparse_night_is_null(tmp_path):
    module()
    from viewer_archive import write_viewer_archive

    from healthviz.analysis.daily import daily_summary
    from healthviz.archive.reader import load_archive

    tables = load_archive(write_viewer_archive(tmp_path))
    daily = daily_summary(tables, tables["devices"], Settings()).set_index("date_local")
    assert daily.loc[date(2026, 1, 1), "resting_hr"] == 55
    assert pd.isna(daily.loc[date(2026, 1, 3), "resting_hr"])


def test_dense_complete_night_gets_app_resting(tmp_path):
    module()
    from fixture_archive import FIXTURE_TABLES, fixture_row
    from viewer_archive import write_viewer_archive

    from healthviz.analysis.daily import daily_summary
    from healthviz.archive.reader import load_archive

    samples = [
        *FIXTURE_TABLES["heart_rate"],
        *[
            fixture_row(
                "heart_rate",
                record_id=f"dense-{m}",
                time_utc=f"2026-01-03T00:{m:02}:00Z",
                utc_offset="+01:00",
                bpm="70",
            )
            for m in range(0, 30, 5)
        ],
    ]
    tables = load_archive(write_viewer_archive(tmp_path, heart_rate=samples))
    daily = daily_summary(tables, tables["devices"], Settings()).set_index("date_local")
    assert daily.loc[date(2026, 1, 3), "resting_hr"] == 70
    assert daily.loc[date(2026, 1, 3), "resting_hr_computed_by"] == "app"
