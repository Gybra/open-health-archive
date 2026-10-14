"""Fictional 130-day archive whose last 30 days differ from the 100 before."""

from copy import deepcopy
from datetime import date, datetime, timedelta

from fixture_archive import FIXTURE_DEVICES, fixture_row

from healthviz.archive.schema import TABLES
from healthviz.archive.writer import write_archive

LAST = date(2026, 6, 30)
DAYS = 130
PERIOD_START = LAST - timedelta(days=29)


def stamp(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_area_archive(root, *, weight_in_period=True, utc_offset="+00:00"):
    tables = {name: [] for name in TABLES if name != "devices"}
    for index in range(DAYS):
        day = LAST - timedelta(days=DAYS - 1 - index)
        recent = day >= PERIOD_START
        wiggle = 1 if index % 2 else -1
        for hour in range(8, 20):
            tables["heart_rate"].append(
                fixture_row(
                    "heart_rate",
                    record_id=f"hr-{index}-{hour}",
                    time_utc=stamp(day, hour),
                    utc_offset=utc_offset,
                    bpm="70",
                )
            )
        tables["steps"].append(
            fixture_row(
                "steps",
                record_id=f"steps-{index}",
                start_utc=stamp(day, 12),
                end_utc=stamp(day, 13),
                utc_offset=utc_offset,
                count=str((9000 if recent else 8000) + 200 * wiggle),
            )
        )
        asleep = (400 if recent else 420) + 10 * wiggle
        tables["sleep_sessions"].append(
            fixture_row(
                "sleep_sessions",
                record_id=f"night-{index}",
                session_id=f"night-{index}",
                start_utc=stamp(day - timedelta(days=1), 23),
                end_utc=stamp(day, 7, 0),
                utc_offset=utc_offset,
                has_stages="false",
                is_complete="true",
                deep_min="90",
                rem_min="100",
                light_min=str(asleep - 190),
                awake_min=str(480 - asleep),
                computed_by="vendor",
            )
        )
        tables["resting_heart_rate"].append(
            fixture_row(
                "resting_heart_rate",
                record_id=f"rest-{index}",
                date_local=day.isoformat(),
                bpm="55",
                computed_by="vendor",
            )
        )
        if index % 7 == 0 and (weight_in_period or not recent):
            tables["weight"].append(
                fixture_row(
                    "weight",
                    record_id=f"weight-{index}",
                    time_utc=stamp(day, 7, 30),
                    utc_offset=utc_offset,
                    kg="69.0" if recent else "70.0",
                )
            )
    write_archive(root, tables, deepcopy(FIXTURE_DEVICES), {}, "synthetic areas")
    return root
