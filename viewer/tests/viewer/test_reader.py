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
    validate = mod.validate_archive
    calls = 0

    def change_after_validation(root):
        nonlocal calls
        errors = validate(root)
        calls += 1
        if calls == 1:
            path.write_text(original.replace(",60,", ",61,"))
        return errors

    monkeypatch.setattr(mod, "validate_archive", change_after_validation)
    with pytest.raises(mod.ArchiveReadError):
        mod.load_archive(root)


def test_safe_csv_path_with_quote(tmp_path):
    root = write_viewer_archive(tmp_path / "quote'folder")
    assert reader().load_archive(root)["heart_rate"].iloc[0]["bpm"] == 60
