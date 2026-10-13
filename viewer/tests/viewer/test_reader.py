import importlib

import pandas as pd
import pytest
from viewer_archive import write_viewer_archive


def reader():
    assert importlib.util.find_spec("healthviz.archive.reader"), "validated reader is missing"
    return importlib.import_module("healthviz.archive.reader")


def test_load_contract_types_and_missing_tables(tmp_path):
    root = write_viewer_archive(tmp_path, spo2=[])
    frames = reader().load_archive(root)
    assert pd.isna(frames["sleep_sessions"].iloc[0]["rem_min"])
    assert str(frames["heart_rate"]["time_utc"].dtype).endswith("UTC]")
    assert frames["heart_rate"].iloc[0]["bpm"] == 60
    assert frames["spo2"].empty
    assert list(frames["spo2"].columns) == [
        "time_utc",
        "utc_offset",
        "percent",
        "device_id",
        "ingest",
        "source_app",
        "record_id",
    ]


def test_read_rejects_corruption_and_midload_change(tmp_path, monkeypatch):
    mod = reader()
    root = write_viewer_archive(tmp_path)
    path = root / "heart_rate/2026-01.csv"
    before = mod.archive_token(root)
    original = path.read_text()
    path.write_text(original.replace(",60,", ",PRIVATE-SENTINEL,"))
    assert mod.archive_token(root) != before
    with pytest.raises(mod.ArchiveReadError) as error:
        mod.load_archive(root)
    assert "PRIVATE-SENTINEL" not in str(error.value)
    path.write_text(original)
    check = mod.check_csv

    def change_after_validation(root, current, *args):
        errors = check(root, current, *args)
        if current == path:
            path.write_text(original.replace(",60,", ",61,"))
        return errors

    monkeypatch.setattr(mod, "check_csv", change_after_validation)
    with pytest.raises(mod.ArchiveReadError):
        mod.load_archive(root)


def test_postload_checksums_reject_same_token_change(tmp_path, monkeypatch):
    import os

    mod = reader()
    root = write_viewer_archive(tmp_path)
    path = root / "heart_rate/2026-01.csv"
    original = path.read_text()
    stat = path.stat()
    token = mod.archive_token(root)
    check = mod.check_csv

    def change_after_validation(root, current, *args):
        errors = check(root, current, *args)
        if current == path:
            path.write_text(original.replace(",60,", ",61,"))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            assert mod.archive_token(root) == token
        return errors

    monkeypatch.setattr(mod, "check_csv", change_after_validation)
    with pytest.raises(mod.ArchiveReadError):
        mod.load_archive(root)


def test_csv_validation_and_checksums_cannot_cover_different_bytes(tmp_path, monkeypatch):
    import hashlib
    import json
    import os

    from healthviz.archive import validate

    mod = reader()
    root = write_viewer_archive(tmp_path)
    path = root / "workouts/2026.csv"
    safe = path.read_bytes()
    unsafe = safe.replace(b"tracks/walk.gpx", b"secret/walk.gpx")
    assert unsafe != safe and len(unsafe) == len(safe)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for entry in manifest["files"]:
        if entry["path"] == "workouts/2026.csv":
            entry["sha256"] = hashlib.sha256(unsafe).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    stat = path.stat()
    check = validate.check_csv

    def swap_after_row_validation(root, current, *args, **kwargs):
        errors = check(root, current, *args, **kwargs)
        if current == path:
            path.write_bytes(unsafe)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return errors

    monkeypatch.setattr(validate, "check_csv", swap_after_row_validation)
    if hasattr(mod, "check_csv"):
        monkeypatch.setattr(mod, "check_csv", swap_after_row_validation)
    with pytest.raises(mod.ArchiveReadError):
        mod.load_archive(root)


def test_parser_buffers_are_sealed_and_closed(tmp_path, monkeypatch):
    import os

    mod = reader()
    root = write_viewer_archive(tmp_path)
    descriptors = []
    create = mod.os.memfd_create
    seal = mod.fcntl.fcntl

    def track_descriptor(*args):
        fd = create(*args)
        descriptors.append(fd)
        return fd

    def check_seals(fd, operation, *args):
        result = seal(fd, operation, *args)
        if operation == mod.fcntl.F_ADD_SEALS:
            with pytest.raises(PermissionError):
                os.write(fd, b"x")
        return result

    monkeypatch.setattr(mod.os, "memfd_create", track_descriptor)
    monkeypatch.setattr(mod.fcntl, "fcntl", check_seals)
    assert mod.load_archive(root)["heart_rate"].iloc[0]["bpm"] == 60
    assert descriptors
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_captured_rows_survive_on_disk_swap_and_restore(tmp_path, monkeypatch):
    import os

    mod = reader()
    root = write_viewer_archive(tmp_path)
    path = root / "workouts/2026.csv"
    safe = path.read_bytes()
    unsafe = safe.replace(b"tracks/walk.gpx", b"secret/walk.gpx")
    stat = path.stat()
    check, typed = mod.check_csv, mod.typed_frame
    events = []

    def swap(root, current, *args):
        errors = check(root, current, *args)
        if current == path:
            path.write_bytes(unsafe)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            events.append("swapped")
        return errors

    def restore_after_materialization(frame):
        if "track_file" in frame and events:
            path.write_bytes(safe)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            events.append("restored")
        return typed(frame)

    monkeypatch.setattr(mod, "check_csv", swap)
    monkeypatch.setattr(mod, "typed_frame", restore_after_materialization)
    frames = mod.load_archive(root)
    assert events == ["swapped", "restored"]
    assert "tracks/walk.gpx" in set(frames["workouts"].track_file.dropna())
    assert "secret/walk.gpx" not in set(frames["workouts"].track_file.dropna())


def test_loader_bounds_descriptors_for_many_partitions(tmp_path):
    import resource

    from fixture_archive import FIXTURE_TABLES

    rows = [
        {
            **FIXTURE_TABLES["heart_rate"][0],
            "time_utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "record_id": f"month-{index}",
        }
        for index, stamp in enumerate(pd.date_range("2010-01-01", periods=100, freq="MS", tz="UTC"))
    ]
    root = write_viewer_archive(tmp_path, heart_rate=rows)
    previous = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, previous[1]))
        frames = reader().load_archive(root)
        assert len(frames["heart_rate"]) == 100
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, previous)


def test_contract_csv_quotes_and_embedded_newlines(tmp_path):
    from copy import deepcopy

    from fixture_archive import FIXTURE_DEVICES, FIXTURE_TABLES, FIXTURE_TRACKS

    from healthviz.archive.writer import write_archive

    model = 'Fixture, "quoted"\nsecond line'
    devices = [{**row, "model": model} for row in FIXTURE_DEVICES]
    write_archive(tmp_path, deepcopy(FIXTURE_TABLES), devices, FIXTURE_TRACKS, "synthetic")
    assert reader().load_archive(tmp_path)["devices"].model.eq(model).all()


def test_safe_csv_path_with_quote(tmp_path):
    root = write_viewer_archive(tmp_path / "quote'folder")
    assert reader().load_archive(root)["heart_rate"].iloc[0]["bpm"] == 60
