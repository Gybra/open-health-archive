from datetime import date

import pandas as pd
import pytest
from resting_archive import APP, write_resting_archive

from healthviz.analysis.apps import select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import load_archive
from healthviz.read_model import load_read_model
from healthviz.settings import Settings


@pytest.fixture
def resting_tables(tmp_path):
    return load_archive(write_resting_archive(tmp_path / "archive"))


def test_supplied_sources_and_estimate_keep_their_actual_provenance(resting_tables):
    daily = daily_summary(resting_tables, resting_tables["devices"], Settings()).set_index(
        "date_local"
    )
    for day, value, ingest in [
        (1, 55, "xiaomi_export"),
        (2, 52, "health_connect"),
        (10, 52, "health_connect"),
    ]:
        row = daily.loc[date(2026, 1, day)]
        assert row.resting_hr == value
        assert row.resting_hr_computed_by == "vendor"
        assert row.resting_hr_ingest == ingest
        assert row.resting_hr_source_app == APP
        assert row.resting_hr_quality == "observed"
    assert not daily.loc[date(2026, 1, 10), "complete"]
    estimate = daily.loc[date(2026, 1, 3)]
    assert estimate.resting_hr == 60
    assert estimate.resting_hr_computed_by == "app"
    assert estimate.resting_hr_quality == "derived from main sleep"
    assert pd.isna(estimate.resting_hr_ingest)
    assert pd.isna(estimate.resting_hr_source_app)


@pytest.mark.parametrize(
    "day,reason",
    [
        (4, "no heart rate samples during main sleep"),
        (5, "fewer than six heart rate samples"),
        (6, "no supported 30-minute window"),
        (7, "main sleep session not eligible"),
        (8, "no main sleep session"),
        (9, "incomplete daily coverage"),
    ],
)
def test_missing_resting_hr_explains_first_blocker(resting_tables, day, reason):
    daily = daily_summary(resting_tables, resting_tables["devices"], Settings()).set_index(
        "date_local"
    )
    row = daily.loc[date(2026, 1, day)]
    assert pd.isna(row.resting_hr)
    assert pd.isna(row.resting_hr_computed_by)
    assert row.resting_hr_quality == f"missing: {reason}"


def test_provenance_follows_source_priority_and_app_filter(resting_tables):
    tables = resting_tables
    supplied = tables["resting_heart_rate"]
    competitor = supplied.loc[supplied.date_local == date(2026, 1, 2)].copy()
    competitor["device_id"] = "fixture-watch-2"
    competitor["source_app"] = "fictional.other"
    competitor["ingest"] = "xiaomi_export"
    competitor["bpm"] = 59
    competitor["record_id"] = "competitor"
    tables = {**tables, "resting_heart_rate": pd.concat([supplied, competitor], ignore_index=True)}
    settings = Settings(
        priority={"resting_heart_rate": ["fixture-watch-2"]},
        device_aliases={"fixture-watch": "fixture-watch-2"},
    )
    row = (
        daily_summary(tables, tables["devices"], settings)
        .set_index("date_local")
        .loc[date(2026, 1, 2)]
    )
    assert row.resting_hr == 59
    assert row.resting_hr_ingest == "xiaomi_export"
    assert row.resting_hr_source_app == "fictional.other"
    chosen = select_apps(tables, ["Mi Fitness"])
    row = (
        daily_summary(chosen, tables["devices"], settings)
        .set_index("date_local")
        .loc[date(2026, 1, 2)]
    )
    assert row.resting_hr == 52
    assert row.resting_hr_ingest == "health_connect"
    assert row.resting_hr_source_app == APP


def test_resting_metadata_round_trips_through_cache(tmp_path):
    root = write_resting_archive(tmp_path / "archive")
    tables = load_archive(root)
    expected = daily_summary(tables, tables["devices"], Settings())
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    config = tmp_path / "config/config.toml"
    for _ in range(2):
        actual = load_read_model(root, Settings(), cache_dir=cache, config=config).daily
        pd.testing.assert_frame_equal(actual, expected)
        assert {"resting_hr_ingest", "resting_hr_source_app"}.issubset(actual.columns)
