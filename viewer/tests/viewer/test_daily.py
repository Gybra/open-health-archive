import importlib

import pandas as pd
from fixture_archive import fixture_row
from viewer_archive import write_viewer_archive

from healthviz.archive.reader import load_archive
from healthviz.settings import Settings


def summary(root):
    assert importlib.util.find_spec("healthviz.analysis.daily"), "daily analysis is missing"
    tables = load_archive(root)
    mod = importlib.import_module("healthviz.analysis.daily")
    return mod.daily_summary(tables, tables["devices"], Settings()).set_index("date_local")


def test_missing_is_not_zero_and_threshold_is_ten(tmp_path):
    daily = summary(write_viewer_archive(tmp_path))
    from datetime import date

    assert daily.loc[date(2026, 1, 1), "worn_hours"] == 1
    assert not daily.loc[date(2026, 1, 1), "complete"]
    assert daily.loc[date(2026, 1, 1), "steps"] == 80
    assert daily.loc[date(2026, 1, 3), "complete"]
    assert pd.isna(daily.loc[date(2026, 1, 2), "steps"])
    assert daily.loc[date(2026, 10, 25), "worn_hours"] == 2


def test_raw_blocks_unknown_source_fallback_per_metric(tmp_path):
    rows = [
        fixture_row(
            "daily_vendor_summaries",
            date_local="2026-01-01",
            metric=metric,
            value=value,
            unit=unit,
            computed_by="vendor",
            device_id="fixture-phone",
            record_id=metric,
        )
        for metric, value, unit in [("steps", "1000", "count"), ("distance", "500", "m")]
    ]
    daily = summary(write_viewer_archive(tmp_path, distance=[], daily_vendor_summaries=rows))
    from datetime import date

    row = daily.loc[date(2026, 1, 1)]
    assert row.steps == 80
    assert row.distance == 500
    assert row.distance_fallback
    assert not row.complete


def test_local_january_reads_december_utc(tmp_path):
    daily = summary(write_viewer_archive(tmp_path))
    from datetime import date

    assert daily.loc[date(2026, 1, 1), "spo2"] == 97.5


def test_weekly_missing_days_and_midnight_duration(tmp_path):
    assert importlib.util.find_spec("healthviz.analysis.daily"), "daily analysis is missing"
    mod = importlib.import_module("healthviz.analysis.daily")
    daily = summary(write_viewer_archive(tmp_path)).reset_index()
    weeks = mod.period_summary(daily, "week")
    assert (weeks["expected_days"] == 7).all()
    assert not weeks["complete"].any()
    assert weeks["covered_days"].max() == 1


def test_same_source_ambiguity_blocks_fallback_and_stats(tmp_path):
    from fixture_archive import FIXTURE_TABLES

    rows = [
        dict(FIXTURE_TABLES["steps"][0]),
        {**FIXTURE_TABLES["steps"][0], "record_id": "overlap"},
    ]
    daily = summary(write_viewer_archive(tmp_path, steps=rows))
    from datetime import date

    assert pd.isna(daily.loc[date(2026, 1, 1), "steps"])
    assert daily.loc[date(2026, 1, 1), "steps_quality"] == "ambiguous"
