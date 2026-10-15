"""Synthetic source transition and resting-HR calculation outcomes, never personal records."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

from fixture_archive import FIXTURE_DEVICES, fixture_row

from healthviz.archive.schema import TABLES
from healthviz.archive.writer import write_archive

FIRST = date(2026, 1, 1)
LAST = date(2026, 1, 10)
APP = "com.xiaomi.wearable"


def write_resting_archive(root):
    tables = {name: [] for name in TABLES if name != "devices"}
    for day in range(1, 11):
        start = datetime(2026, 1, day, tzinfo=UTC)
        provenance = {"ingest": "health_connect", "source_app": APP}
        for hour in range(10, 11 if day >= 9 else 20):
            tables["heart_rate"].append(
                fixture_row(
                    "heart_rate",
                    **provenance,
                    record_id=f"day-{day}-{hour}",
                    time_utc=(start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                    utc_offset="+00:00",
                    bpm="70",
                )
            )
        if day != 8:
            tables["sleep_sessions"].append(
                fixture_row(
                    "sleep_sessions",
                    **provenance,
                    record_id=f"sleep-{day}",
                    session_id=f"sleep-{day}",
                    start_utc=start.isoformat().replace("+00:00", "Z"),
                    end_utc=(start + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    utc_offset="+00:00",
                    has_stages="false",
                    is_complete="false" if day == 7 else "true",
                    light_min="60",
                    computed_by="vendor",
                )
            )
        minutes = (
            range(0, 35, 5)
            if day == 3
            else range(0, 25, 5)
            if day == 5
            else range(0, 60, 10)
            if day == 6
            else []
        )
        for minute in minutes:
            tables["heart_rate"].append(
                fixture_row(
                    "heart_rate",
                    **provenance,
                    record_id=f"night-{day}-{minute}",
                    time_utc=(start + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z"),
                    utc_offset="+00:00",
                    bpm="60",
                )
            )
        if day in (1, 2, 10):
            tables["resting_heart_rate"].append(
                fixture_row(
                    "resting_heart_rate",
                    **{**provenance, "ingest": "xiaomi_export" if day == 1 else "health_connect"},
                    record_id=f"provided-{day}",
                    date_local=start.date().isoformat(),
                    bpm="55" if day == 1 else "52",
                    computed_by="vendor",
                )
            )
    write_archive(root, tables, deepcopy(FIXTURE_DEVICES), {}, "synthetic resting HR")
    return root
