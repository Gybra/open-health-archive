import json
import os
from zoneinfo import ZoneInfo

import pytest
from fixture_archive import fixture_row
from health_connect_export import (
    HOUR_MS,
    JAN,
    OTHER_APP,
    build_export,
    every_type,
    instant,
    interval,
    uuid_hex,
)
from test_writer import snapshot

from healthviz.archive.validate import validate_archive
from healthviz.archive.writer import write_archive
from healthviz.cli import main
from healthviz.health_connect.importer import import_health_connect
from healthviz.health_connect.status import load_status

ROME = ZoneInfo("Europe/Rome")
FEB = JAN + 31 * 24 * HOUR_MS


@pytest.fixture
def places(tmp_path):
    for name in ("downloads", "archive", "config"):
        (tmp_path / name).mkdir()
    return tmp_path


def run(places, zip_name="Health Connect.zip"):
    return import_health_connect(
        places / "downloads",
        places / "archive",
        zone=ROME,
        status=places / "config/status.json",
        journal=places / "config/journal",
        label="~/Downloads",
    )


def export(places, rows, name="Health Connect.zip", mtime=None):
    path = build_export(places / "downloads" / name, rows)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def rows_of(archive, table):
    import csv

    return [
        row
        for path in sorted((archive / table).glob("*.csv"))
        for row in csv.DictReader(path.open(newline=""))
    ]


def steps_export(*records):
    return {"steps_record_table": list(records)}


def test_import_creates_valid_archive(places):
    export(places, every_type())

    status = run(places)

    assert status.error is None
    assert validate_archive(places / "archive") == []
    assert status.counts["steps"] == 1 and status.counts["heart_rate"] == 2
    assert status.folder == "~/Downloads" and status.zip_name == "Health Connect.zip"
    assert load_status(places / "config/status.json") == status
    assert (places / "archive" / f"tracks/{uuid_hex(7)}.gpx").exists()


def test_reimport_is_byte_identical(places):
    export(places, every_type())
    run(places)
    before = snapshot(places / "archive")

    again = run(places)
    assert again.already_imported is True
    export(places, every_type(), name="Health Connect (1).zip", mtime=2_000_000_000)
    copy = run(places)

    assert copy.error is None
    assert snapshot(places / "archive") == before


def test_newer_export_updates_adds_and_deletes(places):
    first = every_type()
    first["steps_record_table"] += [interval(20, JAN + HOUR_MS, JAN + 2 * HOUR_MS, count=50)]
    first["exercise_session_record_table"].append(
        interval(30, JAN + 3 * HOUR_MS, JAN + 4 * HOUR_MS, exercise_type=56)
    )
    first["exercise_session_record_table"].append(
        interval(31, JAN + 5 * HOUR_MS, JAN + 6 * HOUR_MS, exercise_type=56)
    )
    export(places, first, mtime=1_900_000_000)
    run(places)
    second = every_type()
    second["steps_record_table"] = [
        interval(1, JAN, JAN + 600_000, count=900),
        interval(21, JAN + 2 * HOUR_MS, JAN + 3 * HOUR_MS, count=70),
    ]
    # A workout before the deleted ones keeps them inside the period this export covers.
    second["exercise_session_record_table"] = [
        interval(32, JAN - HOUR_MS, JAN - 1_000, exercise_type=56),
        interval(31, JAN + 5 * HOUR_MS, JAN + 6 * HOUR_MS, exercise_type=56),
    ]
    second["exercise_route_table"] = []
    export(places, second, name="Health Connect (1).zip", mtime=2_000_000_000)

    status = run(places)

    assert status.error is None
    steps = {r["record_id"]: r["count"] for r in rows_of(places / "archive", "steps")}
    assert steps == {uuid_hex(1): "900", uuid_hex(21): "70"}
    workouts = {r["workout_id"] for r in rows_of(places / "archive", "workouts")}
    assert workouts == {uuid_hex(31), uuid_hex(32)}
    assert not (places / "archive" / f"tracks/{uuid_hex(7)}.gpx").exists()
    assert validate_archive(places / "archive") == []


def test_retention_shortened_export_keeps_history(places):
    export(
        places,
        steps_export(
            interval(1, JAN, JAN + 60_000, count=5), interval(2, FEB, FEB + 60_000, count=6)
        ),
        mtime=1_900_000_000,
    )
    run(places)
    export(
        places,
        steps_export(
            interval(2, FEB, FEB + 60_000, count=6),
            interval(3, FEB + HOUR_MS, FEB + HOUR_MS + 60_000, count=7),
        ),
        name="b.zip",
        mtime=2_000_000_000,
    )

    run(places)

    assert {r["record_id"] for r in rows_of(places / "archive", "steps")} == {
        uuid_hex(1),
        uuid_hex(2),
        uuid_hex(3),
    }


def test_wiped_app_keeps_its_rows(places):
    other = interval(5, JAN, JAN + 60_000, app_id=2, count=9)
    export(
        places, steps_export(interval(1, JAN, JAN + 60_000, count=5), other), mtime=1_900_000_000
    )
    run(places)
    export(
        places,
        steps_export(
            interval(1, JAN, JAN + 60_000, count=5), interval(2, FEB, FEB + 60_000, count=5)
        ),
        name="b.zip",
        mtime=2_000_000_000,
    )

    run(places)

    apps = {r["record_id"]: r["source_app"] for r in rows_of(places / "archive", "steps")}
    assert apps[uuid_hex(5)] == OTHER_APP


def test_xiaomi_rows_are_never_touched(places):
    xiaomi = fixture_row(
        "steps",
        start_utc="2026-01-01T09:00:00Z",
        end_utc="2026-01-01T09:30:00Z",
        utc_offset="+01:00",
        count="40",
    )
    write_archive(places / "archive", {"steps": [xiaomi]}, [], {}, "test")
    export(places, steps_export(interval(1, JAN - HOUR_MS, JAN + 2 * HOUR_MS, count=5)))

    run(places)

    assert xiaomi in rows_of(places / "archive", "steps")


def test_failed_import_leaves_archive_and_reports(places, capsys):
    export(places, every_type(), mtime=1_900_000_000)
    run(places)
    before = snapshot(places / "archive")
    weights = [instant(n, JAN + n * HOUR_MS, weight=70_000_000.0) for n in range(40, 50)]
    export(places, {"weight_record_table": weights}, name="b.zip", mtime=2_000_000_000)

    status = run(places)

    assert status.error == "implausible weight values; the export format may have changed"
    assert status.last_success["zip_name"] == "Health Connect.zip"
    assert snapshot(places / "archive") == before
    assert load_status(places / "config/status.json").error == status.error


def test_missing_export_is_reported(places):
    status = run(places)

    assert status.error == "no Health Connect export in the chosen folder"


def test_invalid_rows_are_skipped_not_fatal(places):
    zero = interval(1, JAN, JAN, count=5)
    export(places, steps_export(zero, interval(2, JAN, JAN + 60_000, count=5)))

    status = run(places)

    assert status.error is None
    assert status.skipped == {"steps": 1}
    assert validate_archive(places / "archive") == []


def test_status_never_contains_health_values(places):
    export(places, every_type())
    run(places)

    text = (places / "config/status.json").read_text()

    assert "812" not in text and "70.5" not in text and uuid_hex(1) not in text
    assert json.loads(text)["counts"]["steps"] == 1
    assert oct((places / "config/status.json").stat().st_mode & 0o777) == "0o600"


def test_cli_uses_config_timezone(places, capsys):
    (places / "config/config.toml").write_text('default_timezone = "Europe/Rome"\n')
    export(places, steps_export(interval(1, JAN, JAN + 60_000, offset_s=None, count=5)))
    argv = [
        "import",
        "health-connect",
        str(places / "downloads"),
        "--out",
        str(places / "archive"),
        "--status",
        str(places / "config/status.json"),
        "--journal",
        str(places / "config/journal"),
        "--config",
        str(places / "config/config.toml"),
    ]

    assert main(argv) == 0
    assert "steps: 1" in capsys.readouterr().out
    assert rows_of(places / "archive", "steps")[0]["utc_offset"] == "+01:00"
    assert main(argv) == 0
    assert "already imported" in capsys.readouterr().out


def test_cli_failure_exits_one_without_details(places, capsys):
    (places / "downloads/Health Connect.zip").write_bytes(b"SECRET not a zip")
    argv = [
        "import",
        "health-connect",
        str(places / "downloads/Health Connect.zip"),
        "--out",
        str(places / "archive"),
        "--status",
        str(places / "config/status.json"),
        "--journal",
        str(places / "config/journal"),
        "--timezone",
        "Europe/Rome",
    ]

    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err
    assert "import failed: cannot read Health Connect export" in captured.err


def test_write_failure_is_rolled_back_at_once(places, monkeypatch):
    from healthviz.archive import writer

    export(places, every_type(), mtime=1_900_000_000)
    run(places)
    before = snapshot(places / "archive")
    real, calls = writer.atomic_write, []

    def failing(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(writer, "atomic_write", failing)
    newer = every_type()
    newer["steps_record_table"] = [interval(1, JAN, JAN + 600_000, count=999)]
    newer["weight_record_table"] = [instant(10, FEB, weight=71000.0)]
    export(places, newer, name="b.zip", mtime=2_000_000_000)

    status = run(places)

    assert status.error == "cannot read the export or write the archive"
    assert snapshot(places / "archive") == before
    assert not (places / "config/journal").exists()
