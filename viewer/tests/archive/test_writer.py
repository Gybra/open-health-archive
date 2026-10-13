import csv
from pathlib import Path

import pytest
from test_validate import hr

from healthviz.archive.validate import validate_archive
from healthviz.archive.writer import SchemaMismatch, write_archive


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def read_rows(p):
    with p.open() as f:
        return list(csv.DictReader(f))


def test_idempotent_upsert_and_other_sources(tmp_path):
    other = hr(bpm="58", ingest="health_connect")
    write_archive(tmp_path, {"heart_rate": [other, hr()]}, [], {}, "test")
    first = snapshot(tmp_path)
    write_archive(tmp_path, {"heart_rate": [hr()]}, [], {}, "test")
    assert snapshot(tmp_path) == first
    write_archive(tmp_path, {"heart_rate": [hr(bpm="61")]}, [], {}, "test")
    rows = read_rows(tmp_path / "heart_rate/2026-10.csv")
    assert len(rows) == 2 and other in rows and hr(bpm="61") in rows
    assert validate_archive(tmp_path) == []


def test_preflight_aborts_before_any_write(tmp_path):
    (tmp_path / "heart_rate").mkdir()
    target = tmp_path / "heart_rate/2026-10.csv"
    target.write_text("wrong,header\n")
    before = snapshot(tmp_path)
    with pytest.raises(SchemaMismatch):
        write_archive(tmp_path, {"heart_rate": [hr()]}, [], {"tracks/a.gpx": b"x"}, "test")
    assert snapshot(tmp_path) == before


def test_device_ranges_merge(tmp_path):
    device = dict(
        device_id="watch",
        vendor="X",
        model="Watch",
        kind="watch",
        first_seen_utc="2026-01-02T00:00:00Z",
        last_seen_utc="2026-01-03T00:00:00Z",
    )
    write_archive(tmp_path, {}, [device], {}, "test")
    second = {**device, "first_seen_utc": "2026-01-01T00:00:00Z"}
    write_archive(tmp_path, {}, [second], {}, "test")
    assert read_rows(tmp_path / "devices.csv") == [second]


def test_unsafe_track_and_invalid_rows_rejected(tmp_path):
    with pytest.raises(SchemaMismatch):
        write_archive(tmp_path, {}, [], {"../../secret": b"x"}, "test")
    with pytest.raises(SchemaMismatch):
        write_archive(tmp_path, {"heart_rate": [hr(bpm="nan")]}, [], {}, "test")
    assert list(tmp_path.iterdir()) == []


def test_fixture_matches_generator(tmp_path):
    from fixture_archive import FIXTURE_DEVICES, FIXTURE_TABLES, FIXTURE_TRACKS

    write_archive(tmp_path, FIXTURE_TABLES, FIXTURE_DEVICES, FIXTURE_TRACKS, "healthviz fixtures")
    expected = Path("/workspace/schema/fixtures/archive")
    assert snapshot(tmp_path) == snapshot(expected)
    assert validate_archive(expected) == []
