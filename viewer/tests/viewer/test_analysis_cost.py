import cProfile
import pstats
from datetime import date
from unittest.mock import patch

import pandas as pd
from fixture_archive import FIXTURE_TABLES
from viewer_archive import write_viewer_archive

from healthviz.analysis.daily import daily_summary, raw_days
from healthviz.analysis.sources import resolve_rows, split_intervals
from healthviz.archive.reader import load_archive
from healthviz.settings import Settings


def calls(action, function):
    profile = cProfile.Profile()
    result = profile.runcall(action)
    count = sum(
        stats[0] for key, stats in pstats.Stats(profile).stats.items() if key[2] == function
    )
    return result, count


def rows():
    times = pd.date_range("2026-01-03T02:00:00Z", periods=3000, freq="s")
    return pd.DataFrame(
        {
            "start_utc": times,
            "end_utc": times + pd.Timedelta(seconds=1),
            "time_utc": times,
            "utc_offset": "+01:00",
            "device_id": "watch",
            "ingest": "synthetic",
            "source_app": "",
            "record_id": [str(i) for i in range(3000)],
            "bpm": 60,
            "allocation_estimated": False,
        }
    )


def test_single_winner_audit_does_not_dropna_per_sample():
    frame = rows().drop(columns=["start_utc", "end_utc"])
    devices = pd.DataFrame({"device_id": ["watch"], "kind": ["watch"]})
    (selected, audit), count = calls(
        lambda: resolve_rows("heart_rate", frame, devices, Settings()), "dropna"
    )
    assert len(selected) == 3000
    assert audit.winner_id.eq("watch").all()
    assert count < 20, "singleton winners must not allocate/drop a Series per record"


def test_non_crossing_intervals_skip_scalar_iteration():
    frame = rows()
    result, count = calls(
        lambda: split_intervals(frame, pd.DatetimeIndex([pd.Timestamp("2026-01-03T03:00:00Z")])),
        "iterrows",
    )
    assert result.equals(frame)
    assert count < 20, "only intervals crossing boundaries need scalar splitting"


def test_raw_day_blocking_expands_only_cross_midnight_ranges():
    result, count = calls(lambda: raw_days(rows(), "steps", Settings()), "date_range")
    assert result == {date(2026, 1, 3)}
    assert count < 20, "same-day intervals do not need individual date ranges"


def test_reader_parses_csv_rows_only_once(tmp_path):
    root = write_viewer_archive(tmp_path)
    tables, count = calls(lambda: load_archive(root), "check_csv")
    assert len(tables["heart_rate"]) > 0
    assert count == len(list(root.rglob("*.csv")))


def test_vendor_resting_hr_skips_sleep_estimation(tmp_path):
    row = {
        **FIXTURE_TABLES["resting_heart_rate"][0],
        "date_local": "2026-01-03",
        "record_id": "vendor-complete",
        "bpm": "54",
    }
    tables = load_archive(
        write_viewer_archive(
            tmp_path, resting_heart_rate=[*FIXTURE_TABLES["resting_heart_rate"], row]
        )
    )
    from healthviz.analysis.heart import resting_from_sleep

    with patch("healthviz.analysis.daily.resting_from_sleep", wraps=resting_from_sleep) as estimate:
        daily = daily_summary(tables, tables["devices"], Settings())
    assert daily.loc[daily.date_local == date(2026, 1, 3), "resting_hr"].iloc[0] == 54
    assert date(2026, 1, 3) not in set(estimate.call_args.args[1].date_local)
