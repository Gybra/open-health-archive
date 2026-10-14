import csv
from pathlib import Path

import pytest
from test_validate import hr

from healthviz.archive.validate import validate_archive
from healthviz.archive.writer import SchemaMismatch, recover_archive, write_archive


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


def two_track_archive(root):
    from fixture_archive import GPX

    tracks = {"tracks/a.gpx": GPX, "tracks/b.gpx": GPX}
    write_archive(root, {"heart_rate": [hr()]}, [], tracks, "test")


def test_delete_tracks_removes_file_and_manifest_entry(tmp_path):
    two_track_archive(tmp_path)

    write_archive(tmp_path, {}, [], {}, "test", delete_tracks={"tracks/a.gpx"})

    assert not (tmp_path / "tracks/a.gpx").exists()
    assert (tmp_path / "tracks/b.gpx").exists()
    assert "tracks/a.gpx" not in (tmp_path / "manifest.json").read_text()
    assert validate_archive(tmp_path) == []


def test_delete_tracks_rejects_unsafe_paths(tmp_path):
    two_track_archive(tmp_path)
    before = snapshot(tmp_path)

    with pytest.raises(SchemaMismatch):
        write_archive(tmp_path, {}, [], {}, "test", delete_tracks={"../x.gpx"})

    assert snapshot(tmp_path) == before


def test_interrupted_write_is_rolled_back_next_run(tmp_path, monkeypatch):
    from healthviz.archive import writer

    root, journal = tmp_path / "archive", tmp_path / "journal"
    two_track_archive(root)
    before = snapshot(root)
    real, calls = writer.atomic_write, []

    def failing(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(writer, "atomic_write", failing)
    rows = {"heart_rate": [hr(bpm="70"), hr(time_utc="2026-11-01T00:00:00Z", record_id="n")]}
    with pytest.raises(OSError):
        write_archive(root, rows, [], {}, "test", delete_tracks={"tracks/a.gpx"}, journal=journal)
    monkeypatch.setattr(writer, "atomic_write", real)
    assert validate_archive(root) != []
    with pytest.raises(SchemaMismatch):
        write_archive(root, {}, [], {}, "test", journal=journal)

    assert recover_archive(root, journal) is True

    assert snapshot(root) == before
    assert validate_archive(root) == []
    assert not journal.exists()


def test_recover_without_journal_is_noop(tmp_path):
    two_track_archive(tmp_path / "archive")
    before = snapshot(tmp_path / "archive")

    assert recover_archive(tmp_path / "archive", tmp_path / "journal") is False
    assert snapshot(tmp_path / "archive") == before


def test_journal_removed_after_success(tmp_path):
    journal = tmp_path / "journal"

    write_archive(tmp_path / "archive", {"heart_rate": [hr()]}, [], {}, "test", journal=journal)

    assert not journal.exists()
    assert validate_archive(tmp_path / "archive") == []


def leave_journal_after_complete_write(root, journal, monkeypatch):
    from healthviz.archive import writer

    monkeypatch.setattr(writer, "discard_journal", lambda path: None)
    write_archive(root, {"heart_rate": [hr(bpm="70")]}, [], {}, "test", journal=journal)
    monkeypatch.undo()
    assert (journal / "entries.json").exists()


def test_journal_of_a_completed_write_is_discarded(tmp_path, monkeypatch):
    root, journal = tmp_path / "archive", tmp_path / "journal"
    two_track_archive(root)
    leave_journal_after_complete_write(root, journal, monkeypatch)
    # Another importer writes in between; its rows must survive.
    write_archive(root, {"heart_rate": [hr(ingest="xiaomi_export", record_id="x")]}, [], {}, "t")
    after = snapshot(root)

    assert recover_archive(root, journal) is False

    assert snapshot(root) == after
    assert not journal.exists()


def test_journal_is_never_replayed_onto_another_archive(tmp_path, monkeypatch):
    first, other, journal = tmp_path / "a", tmp_path / "b", tmp_path / "journal"
    two_track_archive(first)
    leave_journal_after_complete_write(first, journal, monkeypatch)
    write_archive(other, {"heart_rate": [hr(record_id="other")]}, [], {}, "test")
    before = snapshot(other)

    assert recover_archive(other, journal) is False

    assert snapshot(other) == before


def test_torn_journal_is_discarded(tmp_path):
    root, journal = tmp_path / "archive", tmp_path / "journal"
    two_track_archive(root)
    (journal / "blobs").mkdir(parents=True)
    (journal / "entries.json").write_text('[{"path": "heart')
    before = snapshot(root)

    assert recover_archive(root, journal) is False

    assert snapshot(root) == before and not journal.exists()
