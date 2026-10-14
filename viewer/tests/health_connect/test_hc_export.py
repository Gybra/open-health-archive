import os
import zipfile

import pytest
from health_connect_export import JAN, build_export, interval

from healthviz.health_connect import export as export_module
from healthviz.health_connect.export import ExportError, newest_export, open_export


def steps(n=1, count=100):
    return interval(n, JAN, JAN + 600_000, count=count)


def test_newest_health_connect_zip_wins(tmp_path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    assert newest_export(folder) is None
    with zipfile.ZipFile(folder / "other.zip", "w") as other:
        other.writestr("notes.txt", "x")
    older = build_export(folder / "Health Connect (1).zip", {})
    newer = build_export(folder / "Health Connect.zip", {})
    (folder / "x.zip.crdownload").write_bytes(b"partial")
    os.utime(older, (2_000_000_000, 2_000_000_000))
    os.utime(newer, (1_900_000_000, 1_900_000_000))
    os.utime(folder / "other.zip", (2_100_000_000, 2_100_000_000))

    assert newest_export(folder) == older


def test_only_expected_member_is_extracted(tmp_path):
    zip_path = build_export(tmp_path / "export.zip", {"steps_record_table": [steps()]})
    with zipfile.ZipFile(zip_path, "a") as archive:
        archive.writestr("../evil", "x")
        archive.writestr("x.db", "x")
    work = tmp_path / "work"
    work.mkdir()

    with open_export(zip_path, work) as export:
        assert list(export.rows("steps_record_table", ("count",))) == [(100,)]

    assert not (tmp_path / "evil").exists()
    assert sorted(p.name for p in work.iterdir()) == ["health_connect_export.db"]


def test_oversized_member_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(export_module, "MAX_DB_BYTES", 1024)
    zip_path = build_export(tmp_path / "export.zip", {})

    with pytest.raises(ExportError, match="^Health Connect export is too large$"):
        with open_export(zip_path, tmp_path):
            pass


def test_missing_column_is_unsupported(tmp_path):
    zip_path = build_export(tmp_path / "export.zip", {})
    database = tmp_path / "work.db"
    with zipfile.ZipFile(zip_path) as archive:
        database.write_bytes(archive.read("health_connect_export.db"))
    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE steps_record_table DROP COLUMN count")
    connection.close()
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.write(database, "health_connect_export.db")
    work = tmp_path / "work"
    work.mkdir()

    with pytest.raises(ExportError, match="^unsupported Health Connect export format$"):
        with open_export(broken, work):
            pass


def test_unknown_version_with_matching_columns_opens_untested(tmp_path):
    zip_path = build_export(tmp_path / "export.zip", {}, user_version=27)

    with open_export(zip_path, tmp_path) as export:
        assert export.format_version == 27
        assert export.format_tested is False


def test_known_version_is_tested_and_exposes_provenance(tmp_path):
    zip_path = build_export(tmp_path / "export.zip", {})

    with open_export(zip_path, tmp_path) as export:
        assert export.format_tested is True
        assert export.apps[1] == "com.xiaomi.wearable"
        assert export.devices[2] == ("Phone", "P1", 2)


def test_not_a_zip_is_reported_without_details(tmp_path):
    bogus = tmp_path / "Health Connect.zip"
    bogus.write_bytes(b"SECRET-CONTENT not a zip")

    with pytest.raises(ExportError) as raised:
        with open_export(bogus, tmp_path):
            pass

    assert str(raised.value) == "cannot read Health Connect export"


def test_not_imported_counts_unmapped_tables(tmp_path):
    elevation = interval(7, JAN, JAN + 60_000, elevation=12.0)
    zip_path = build_export(tmp_path / "export.zip", {"elevation_gained_record_table": [elevation]})

    with open_export(zip_path, tmp_path) as export:
        assert export.not_imported() == {"elevation_gained": 1}


def test_children_are_grouped_by_parent(tmp_path):
    rows = {
        "heart_rate_record_table": [interval(1, JAN, JAN + 120_000)],
        "heart_rate_record_series_table": [
            dict(parent_key=1, beats_per_minute=61, epoch_millis=JAN + 60_000),
            dict(parent_key=1, beats_per_minute=60, epoch_millis=JAN),
        ],
    }
    zip_path = build_export(tmp_path / "export.zip", rows)

    with open_export(zip_path, tmp_path) as export:
        children = export.children(
            "heart_rate_record_series_table", "parent_key", ("epoch_millis", "beats_per_minute")
        )

    assert children == {1: [(JAN, 60), (JAN + 60_000, 61)]}


def test_callers_errors_are_not_relabelled(tmp_path):
    zip_path = build_export(tmp_path / "export.zip", {})

    with pytest.raises(KeyError):
        with open_export(zip_path, tmp_path):
            raise KeyError("bug in the caller")


def test_corrupt_compressed_member_is_reported(tmp_path):
    plain = build_export(tmp_path / "plain.zip", {"steps_record_table": [steps()]})
    with zipfile.ZipFile(plain) as source:
        data = source.read("health_connect_export.db")
    packed = tmp_path / "packed.zip"
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("health_connect_export.db", data)
    raw = bytearray(packed.read_bytes())
    middle = len(raw) // 2
    raw[middle : middle + 64] = bytes(64)
    packed.write_bytes(bytes(raw))
    work = tmp_path / "work"
    work.mkdir()

    with pytest.raises(ExportError, match="^cannot read Health Connect export$"):
        with open_export(packed, work):
            pass
