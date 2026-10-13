import shutil

import pytest
from xiaomi_export import WATCH_SID, fitness_row, write_export

from healthviz.xiaomi.devices import load_devices
from healthviz.xiaomi.source import ExportError, open_export


def test_dir_and_zip(tmp_path):
    export = write_export(
        tmp_path / "x", fitness=[fitness_row("heart_rate", 1767225600, {"bpm": 60})]
    )
    zipped = shutil.make_archive(str(tmp_path / "zip"), "zip", export)
    for path in (export, zipped):
        rowno, row = next(open_export(path).rows("fitness_data"))
        assert rowno == 1 and row["Key"] == "heart_rate"


def test_required_missing(tmp_path):
    export = write_export(tmp_path)
    next(export.glob("*_hlth_center_fitness_data.csv")).unlink()
    with pytest.raises(ExportError, match="fitness_data"):
        open_export(export)


def test_bad_header(tmp_path):
    p = write_export(tmp_path)
    next(p.glob("*_hlth_center_fitness_data.csv")).write_text("Uid,Time\n")
    with pytest.raises(ExportError, match="columns"):
        open_export(p)


def test_optional_missing_and_json_privacy(tmp_path):
    p = write_export(tmp_path)
    next(p.glob("*sport_record.csv")).unlink()
    e = open_export(p)
    assert list(e.rows("sport_record")) == []
    assert e.json_value("fitness_data", 3, '{"bpm": SECRET') is None
    assert "SECRET" not in str(e.warnings)
    assert len(e.warnings) == 2


def test_device_rules(tmp_path):
    p = write_export(tmp_path)
    devices = load_devices(open_export(p))
    assert devices[WATCH_SID].device_id == "xiaomi-watch-s1-active"
    assert devices[WATCH_SID].kind == "watch"
    assert devices["901"].device_id == "mi-fitness-manual"
