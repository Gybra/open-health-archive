from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fixture_archive import FIXTURE_DEVICES, fixture_row

from healthviz import read_model
from healthviz.analysis.heart import max_hr
from healthviz.analysis.observations import observations
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.schema import TABLES
from healthviz.archive.writer import write_archive
from healthviz.read_model import load_read_model
from healthviz.settings import Settings


def test_health_connect_only_update_keeps_history_without_filling_missing_days(tmp_path):
    from zoneinfo import ZoneInfo

    from health_connect_export import HOUR_MS, build_export, instant, interval
    from resting_archive import write_resting_archive

    from healthviz.analysis.daily import daily_summary
    from healthviz.archive.reader import load_archive
    from healthviz.health_connect.importer import import_health_connect

    root = write_resting_archive(tmp_path / "archive")
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    config = tmp_path / "config/config.toml"
    before = load_read_model(root, Settings(), cache_dir=cache, config=config).daily
    start = int(datetime(2026, 1, 11, tzinfo=UTC).timestamp() * 1000)
    export = build_export(
        tmp_path / "new.zip",
        {
            "heart_rate_record_table": [
                interval(700, start + 10 * HOUR_MS, start + 20 * HOUR_MS, offset_s=0)
            ],
            "heart_rate_record_series_table": [
                dict(parent_key=700, beats_per_minute=70, epoch_millis=start + hour * HOUR_MS)
                for hour in range(10, 20)
            ],
            "sleep_session_record_table": [interval(701, start, start + HOUR_MS, offset_s=0)],
            "sleep_stages_table": [
                dict(
                    parent_key=701,
                    stage_start_time=start,
                    stage_end_time=start + HOUR_MS,
                    stage_type=4,
                )
            ],
            "resting_heart_rate_record_table": [
                instant(702, start + 34 * HOUR_MS, offset_s=0, beats_per_minute=54)
            ],
        },
    )
    status = import_health_connect(
        export,
        root,
        zone=ZoneInfo("UTC"),
        status=tmp_path / "status.json",
        journal=tmp_path / "journal",
    )
    assert status.error is None
    tables = load_archive(root)
    expected = daily_summary(tables, tables["devices"], Settings())
    for _ in range(2):
        actual = load_read_model(root, Settings(), cache_dir=cache, config=config).daily
        pd.testing.assert_frame_equal(actual, expected)
    # Later missing metrics can promote integer columns to float without changing history.
    pd.testing.assert_frame_equal(
        expected.iloc[:10].reset_index(drop=True), before, check_dtype=False
    )
    daily = expected.set_index("date_local")
    assert daily.loc[date(2026, 1, 1), "resting_hr"] == 55
    assert daily.loc[date(2026, 1, 1), "resting_hr_ingest"] == "xiaomi_export"
    assert daily.loc[date(2026, 1, 3), "resting_hr"] == 60
    missing = daily.loc[date(2026, 1, 11)]
    assert missing.complete
    assert pd.isna(missing.resting_hr)
    assert missing.resting_hr_quality == "missing: no heart rate samples during main sleep"
    supplied = daily.loc[date(2026, 1, 12)]
    assert supplied.resting_hr == 54
    assert supplied.resting_hr_ingest == "health_connect"
    assert supplied.resting_hr_computed_by == "vendor"


def test_nonempty_historical_answers_match_cold_and_persistent_hit(tmp_path):
    tables = {name: [] for name in TABLES if name != "devices"}
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for day in range(75):
        instant = start + timedelta(days=day)
        local = instant.strftime("%Y-%m-%d")
        for hour in range(24):
            tables["heart_rate"].append(
                fixture_row(
                    "heart_rate",
                    time_utc=(instant + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    utc_offset="+00:00",
                    bpm="60",
                    record_id=f"hour-{day}-{hour}",
                )
            )
        tables["resting_heart_rate"].append(
            fixture_row(
                "resting_heart_rate",
                date_local=local,
                bpm="70" if day == 15 else "50",
                computed_by="vendor" if day < 40 else "app",
                record_id=f"resting-{day}",
            )
        )
        tables["sleep_sessions"].append(
            fixture_row(
                "sleep_sessions",
                session_id=f"night-{day}",
                start_utc=local + "T00:00:00Z",
                end_utc=local + "T09:00:00Z",
                utc_offset="+00:00",
                has_stages="false",
                is_complete="true",
                deep_min="120",
                light_min="300",
                rem_min="60",
                awake_min="60",
                computed_by="vendor",
                record_id=f"night-{day}",
            )
        )
    for day, peak, distance in [(9, 151, 2000), (31, 226, 50000)]:
        instant = start + timedelta(days=day, hours=10)
        for index, bpm in enumerate([peak - 1, peak, peak - 1, peak]):
            tables["heart_rate"].append(
                fixture_row(
                    "heart_rate",
                    time_utc=(instant + timedelta(seconds=(index + 1) * 30)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    utc_offset="+00:00",
                    bpm=str(bpm),
                    record_id=f"peak-{day}-{index}",
                )
            )
        tables["workouts"].append(
            fixture_row(
                "workouts",
                workout_id=f"workout-{day}",
                type="walking",
                start_utc=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end_utc=(instant + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                utc_offset="+00:00",
                duration_s="1800",
                distance_m=str(distance),
                record_id=f"workout-{day}",
            )
        )
    root = tmp_path / "archive"
    write_archive(root, tables, deepcopy(FIXTURE_DEVICES), {}, "synthetic")
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    settings = Settings()
    config = tmp_path / "config/config.toml"
    cold = load_read_model(root, settings, cache_dir=cache, config=config)
    recompute = AssertionError("persistent hit must not recompute")
    with (
        patch.object(read_model, "load_archive", side_effect=recompute),
        patch.object(read_model, "daily_summary", side_effect=recompute),
        patch.object(read_model, "resolve_rows", side_effect=recompute),
    ):
        hit = load_read_model(root, settings, cache_dir=cache, config=config)
    for as_of in [date(2026, 1, 16), date(2026, 2, 10), date(2026, 3, 10)]:
        messages = observations(cold.daily, cold.sleep, cold.workouts, as_of)
        assert messages, "eligible synthetic history must produce actual observations"
        assert messages == observations(hit.daily, hit.sleep, hit.workouts, as_of)
        if as_of == date(2026, 1, 16):
            assert any("preceding 30-day mean" in message for message in messages)
            assert not any("2026-02-01" in message for message in messages)
    for as_of, expected in [(date(2026, 1, 16), 151), (date(2026, 2, 10), 226)]:
        for model in (cold, hit):
            hr, _ = resolve_rows(
                "heart_rate", model.tables["heart_rate"], model.tables["devices"], settings
            )
            maximum, method = max_hr(settings, hr, model.workouts, as_of)
            assert maximum == pytest.approx(expected) and method == "observed"
