from zoneinfo import ZoneInfo

import pytest
from health_connect_export import (
    HOUR_MS,
    JAN,
    build_export,
    every_type,
    instant,
    interval,
    uuid_hex,
)

from healthviz.archive.gpx import validate_gpx
from healthviz.archive.schema import TABLES
from healthviz.archive.validate import validate_row
from healthviz.health_connect.export import ExportError, open_export
from healthviz.health_connect.mapping import map_export

ROME = ZoneInfo("Europe/Rome")
JULY = 1_783_000_000_000  # 2026-07-02T13:46:40Z, Rome is +02:00


def mapped(tmp_path, rows, zone=ROME):
    zip_path = build_export(tmp_path / "export.zip", rows)
    work = tmp_path / "work"
    work.mkdir()
    with open_export(zip_path, work) as export:
        return map_export(export, zone)


def test_every_mapped_type_produces_valid_rows(tmp_path):
    result = mapped(tmp_path, every_type())

    for name, rows in result.tables.items():
        for row in rows:
            assert validate_row(TABLES[name], row) == [], name
    steps = result.tables["steps"][0]
    assert steps["record_id"] == uuid_hex(1)
    assert (steps["start_utc"], steps["end_utc"], steps["utc_offset"]) == (
        "2026-01-01T09:00:00Z",
        "2026-01-01T09:10:00Z",
        "+01:00",
    )
    assert steps["count"] == "812"
    assert steps["ingest"] == "health_connect"
    assert steps["source_app"] == "com.xiaomi.wearable"
    assert result.tables["distance"][0]["distance_m"] == "640.0"
    calories = {row["kind"]: row["kcal"] for row in result.tables["calories"]}
    assert calories == {"active": "250.0", "total": "1800.0"}
    assert result.tables["spo2"][0]["percent"] == "97.0"
    assert result.tables["weight"][0]["kg"] == "70.5"
    resting = result.tables["resting_heart_rate"][0]
    assert (resting["date_local"], resting["bpm"], resting["computed_by"]) == (
        "2026-01-01",
        "52",
        "vendor",
    )
    session = result.tables["sleep_sessions"][0]
    assert (session["session_id"], session["has_stages"], session["computed_by"]) == (
        uuid_hex(6),
        "true",
        "vendor",
    )
    assert session["deep_min"] == session["is_complete"] == ""
    stages = [(r["stage"], r["source_type"]) for r in result.tables["sleep_stages"]]
    assert stages == [("deep", "deep"), ("rem", "rem")]
    workout = result.tables["workouts"][0]
    assert (workout["workout_id"], workout["type"], workout["source_type"]) == (
        uuid_hex(7),
        "walking",
        "walking",
    )
    assert workout["track_file"] == f"tracks/{uuid_hex(7)}.gpx"
    assert workout["duration_s"] == workout["active_kcal"] == ""


def test_heart_rate_samples_get_child_ids(tmp_path):
    result = mapped(tmp_path, every_type())

    rows = result.tables["heart_rate"]
    assert [r["record_id"] for r in rows] == [
        f"{uuid_hex(5)}@{JAN}",
        f"{uuid_hex(5)}@{JAN + 60_000}",
    ]
    assert [(r["time_utc"], r["bpm"], r["utc_offset"]) for r in rows] == [
        ("2026-01-01T09:00:00Z", "61", "+01:00"),
        ("2026-01-01T09:01:00Z", "64", "+01:00"),
    ]


def test_missing_offset_uses_zone(tmp_path):
    rows = {"steps_record_table": [interval(1, JULY, JULY + 1_500, offset_s=None, count=5)]}

    step = mapped(tmp_path, rows).tables["steps"][0]

    assert step["utc_offset"] == "+02:00"
    assert step["end_utc"] == "2026-07-02T13:46:42Z"  # 1.5 s rounds the end up


def test_device_pseudonym_hides_system_id(tmp_path):
    rows = {
        "steps_record_table": [
            interval(1, JAN, JAN + 60_000, app_id=1, device_id=1, count=5),
            interval(2, JAN, JAN + 60_000, app_id=3, device_id=2, count=5),
            interval(3, JAN, JAN + 60_000, app_id=2, device_id=1, count=5),
            interval(4, JAN, JAN + 60_000, app_id=2, device_id=None, count=5),
        ]
    }

    result = mapped(tmp_path, rows)

    assert "SYSTEM-DEVICE-ID" not in repr(result)
    kinds = {
        row["source_app"]: result.devices[row["device_id"]].kind
        for row in result.tables["steps"][:3]
    }
    assert kinds == {
        "com.xiaomi.wearable": "watch",
        "com.android.healthconnect.phone.0123abcd": "phone",
        "org.example.tracker": "other",
    }
    assert result.devices[result.tables["steps"][3]["device_id"]].kind == "app"
    assert all(d.startswith("hc-") and len(d) == 19 for d in result.devices)


def test_route_becomes_gpx(tmp_path):
    rows = every_type()
    rows["exercise_session_record_table"].append(interval(11, JAN, JAN + HOUR_MS, exercise_type=56))

    result = mapped(tmp_path, rows)

    track = result.tracks[f"tracks/{uuid_hex(7)}.gpx"]
    validate_gpx(track)
    assert track.count(b"<trkpt") == 3
    assert track.count(b"<ele>") == 2  # the sentinel altitude stays absent
    without = next(w for w in result.tables["workouts"] if w["workout_id"] == uuid_hex(11))
    assert without["track_file"] == ""
    assert without["type"] == "running"


def test_unknown_enums_are_kept_as_source_type(tmp_path):
    rows = {
        "exercise_session_record_table": [interval(1, JAN, JAN + HOUR_MS, exercise_type=999)],
        "sleep_session_record_table": [interval(2, JAN - HOUR_MS, JAN)],
        "sleep_stages_table": [
            dict(parent_key=2, stage_start_time=JAN - HOUR_MS, stage_end_time=JAN, stage_type=99)
        ],
    }

    result = mapped(tmp_path, rows)

    assert (result.tables["workouts"][0]["type"], result.tables["workouts"][0]["source_type"]) == (
        "other_workout",
        "999",
    )
    assert (
        result.tables["sleep_stages"][0]["stage"],
        result.tables["sleep_stages"][0]["source_type"],
    ) == ("unknown", "99")


def test_outlier_is_skipped_and_counted(tmp_path):
    weights = [instant(n, JAN + n * HOUR_MS, weight=70000.0) for n in range(1, 400)]
    weights.append(instant(400, JAN, weight=7_000_000.0))

    result = mapped(tmp_path, {"weight_record_table": weights})

    assert len(result.tables["weight"]) == 399
    assert result.skipped == {"weight": 1}


def test_unit_change_stops_import(tmp_path):
    weights = [instant(n, JAN + n * HOUR_MS, weight=70_000_000.0) for n in range(1, 10)]

    with pytest.raises(
        ExportError, match="^implausible weight values; the export format may have changed$"
    ):
        mapped(tmp_path, {"weight_record_table": weights})


def test_notes_and_titles_are_not_exported(tmp_path):
    result = mapped(tmp_path, every_type())

    text = repr(result.tables)
    assert "PRIVATE-NOTE" not in text and "PRIVATE-TITLE" not in text


def test_unconvertible_records_are_skipped_and_counted(tmp_path):
    rows = every_type()
    rows["steps_record_table"] += [
        interval(40, JAN, JAN + 60_000, offset_s=20 * 3600, count=5),
        interval(41, JAN, JAN + 60_000, count=None),
    ]
    rows["active_calories_burned_record_table"].append(
        interval(42, JAN, JAN + 60_000, energy=float("nan"))
    )
    rows["heart_rate_record_series_table"].append(
        dict(parent_key=5, beats_per_minute=None, epoch_millis=JAN + 90_000)
    )

    result = mapped(tmp_path, rows)

    assert result.skipped == {"steps": 2, "calories": 1, "heart_rate": 1}
    assert len(result.tables["steps"]) == 1 and len(result.tables["heart_rate"]) == 2
