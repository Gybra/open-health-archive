import csv
import hashlib
import json

import pytest

from healthviz.archive.schema import TABLES, partition_path
from healthviz.archive.validate import validate_archive, validate_row


def hr(**changes):
    return {
        "time_utc": "2026-10-12T06:30:00Z",
        "utc_offset": "+02:00",
        "bpm": "60",
        "device_id": "fixture-watch",
        "ingest": "xiaomi_export",
        "source_app": "",
        "record_id": "a",
        **changes,
    }


def write_csv(root, table, rows, path=None):
    path = root / (path or partition_path(TABLES[table], rows[0]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, TABLES[table].columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    manifest = {
        "schema_version": 1,
        "generator": "test",
        "files": [
            {
                "path": str(p.relative_to(root)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "rows": len(rows),
            }
            for p in root.rglob("*.csv")
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return path


def test_partitions():
    assert partition_path(TABLES["heart_rate"], hr()) == "heart_rate/2026-10.csv"
    assert (
        partition_path(TABLES["workouts"], {"start_utc": hr()["time_utc"]}) == "workouts/2026.csv"
    )
    assert (
        partition_path(TABLES["resting_heart_rate"], {"date_local": "2026-10-12"})
        == "resting_heart_rate/2026.csv"
    )
    assert partition_path(TABLES["devices"], {}) == "devices.csv"


def test_valid_archive(tmp_path):
    write_csv(tmp_path, "heart_rate", [hr()])
    assert validate_archive(tmp_path) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("bpm", ""),
        ("bpm", "abc"),
        ("bpm", "nan"),
        ("bpm", "-2"),
        ("time_utc", "bad"),
        ("utc_offset", "+02:99"),
        ("device_id", ""),
    ],
)
def test_bad_row(field, value):
    assert validate_row(TABLES["heart_rate"], hr(**{field: value}))


def test_bad_header(tmp_path):
    path = write_csv(tmp_path, "heart_rate", [hr()])
    path.write_text("wrong,header\n")
    assert any("header" in e for e in validate_archive(tmp_path))


def test_wrong_partition(tmp_path):
    write_csv(tmp_path, "heart_rate", [hr()], "heart_rate/2026-09.csv")
    assert any("partition" in e for e in validate_archive(tmp_path))


def test_duplicate(tmp_path):
    write_csv(tmp_path, "heart_rate", [hr(), hr()])
    assert any("duplicate" in e for e in validate_archive(tmp_path))


def test_manifest_mismatch(tmp_path):
    path = write_csv(tmp_path, "heart_rate", [hr()])
    path.write_text(path.read_text().replace(",60,", ",61,"))
    assert any("checksum" in e for e in validate_archive(tmp_path))


def test_unlisted_file(tmp_path):
    write_csv(tmp_path, "heart_rate", [hr()])
    (tmp_path / "extra.csv").write_text("hello\n")
    assert any("file list" in e for e in validate_archive(tmp_path))


def test_missing_track_and_reversed_interval():
    t = TABLES["workouts"]
    row = dict.fromkeys(t.columns, "")
    row.update(
        workout_id="a",
        type="walking",
        start_utc="2026-01-01T01:00:00Z",
        end_utc="2026-01-01T00:00:00Z",
        utc_offset="+01:00",
        device_id="x",
        ingest="test",
        record_id="x",
    )
    assert any("interval" in e for e in validate_row(t, row))


def test_rejects_unsafe_track_reference():
    t = TABLES["workouts"]
    row = dict.fromkeys(t.columns, "")
    row.update(
        workout_id="a",
        type="walking",
        start_utc="2026-01-01T00:00:00Z",
        end_utc="2026-01-01T01:00:00Z",
        utc_offset="+01:00",
        device_id="x",
        ingest="test",
        record_id="x",
        track_file="../../secret",
    )
    assert any("track_file" in e for e in validate_row(t, row))
