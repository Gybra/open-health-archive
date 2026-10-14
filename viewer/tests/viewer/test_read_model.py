import importlib
import importlib.util
import json
import os
from dataclasses import replace
from datetime import date
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest
from viewer_archive import write_viewer_archive

from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import load_archive
from healthviz.settings import Settings


def module():
    assert importlib.util.find_spec("healthviz.read_model"), "persistent read model is missing"
    return importlib.import_module("healthviz.read_model")


def prepare(tmp_path, **rows):
    root = write_viewer_archive(tmp_path / "archive", **rows)
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    return root, cache, tmp_path / "config/config.toml"


def test_fresh_hit_matches_frames_without_recomputing(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path, spo2=[])
    tables = load_archive(root)
    expected = daily_summary(tables, tables["devices"], Settings())
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert first.daily.set_index("date_local").loc[date(2026, 1, 1), "steps"] == 80
    pd.testing.assert_frame_equal(first.daily, expected)
    with (
        patch.object(mod, "load_archive", side_effect=AssertionError("reparsed CSV")),
        patch.object(mod, "daily_summary", side_effect=AssertionError("recomputed daily")),
        patch.object(mod, "resolve_rows", side_effect=AssertionError("resolved sources")),
    ):
        hit = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    for name, frame in tables.items():
        pd.testing.assert_frame_equal(hit.tables[name], frame)
    for name in ("daily", "sleep", "workouts"):
        pd.testing.assert_frame_equal(getattr(hit, name), getattr(first, name))


@pytest.mark.parametrize(
    "changes",
    [
        {"worn_hours_threshold": 11},
        {"default_timezone": "Europe/Rome"},
        {"birth_year": 2000},
        {"max_hr": 180.0},
        {"archive_dir": "/archive"},
        {"priority": {"steps": ["fixture-phone"]}},
        {"ingest_priority": {"fixture-watch": ["health_connect"]}},
        {"device_aliases": {"fixture-watch-2": "fixture-watch"}},
    ],
)
def test_settings_rebuild_only_derivatives(tmp_path, changes):
    mod = module()
    root, cache, config = prepare(tmp_path)
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    settings = replace(Settings(), **changes)
    with patch.object(mod, "load_archive", side_effect=AssertionError("reparsed identical CSV")):
        changed = mod.load_read_model(root, settings, cache_dir=cache, config=config)
    expected = daily_summary(first.tables, first.tables["devices"], settings)
    pd.testing.assert_frame_equal(changed.daily, expected)


@pytest.mark.parametrize(
    "corruption", ["bytes", "metadata", "view", "wal", "pointer", "frames-type", "missing-daily"]
)
def test_corrupt_cache_rebuilds_from_valid_sources(tmp_path, corruption):
    mod = module()
    root, cache, config = prepare(tmp_path)
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    pointer = cache / "current.json"
    state = json.loads(pointer.read_bytes())
    path = cache / state["file"]
    if corruption == "bytes":
        path.write_bytes(b"not a database")
    elif corruption == "pointer":
        pointer.write_text("invalid JSON")
    elif corruption == "wal":
        (cache / (state["file"] + ".wal")).write_bytes(b"interrupted")
    else:
        with duckdb.connect(str(path)) as conn:
            if corruption == "view":
                conn.execute("CREATE VIEW unexpected AS SELECT 1")
            else:
                metadata = json.loads(
                    conn.execute("SELECT payload FROM healthviz_meta").fetchone()[0]
                )
                if corruption == "frames-type":
                    metadata["frames"] = list(metadata["frames"])
                elif corruption == "missing-daily":
                    conn.execute(
                        "CREATE OR REPLACE TABLE derived_daily AS SELECT _order FROM derived_daily"
                    )
                    metadata["frames"]["derived_daily"]["columns"] = []
                else:
                    metadata["frames"]["steps"]["rows"] += 1
                conn.execute("UPDATE healthviz_meta SET payload = ?", [json.dumps(metadata)])
        state["sha256"] = mod.file_checksum(path)
        pointer.write_text(json.dumps(state))
    with patch.object(mod, "load_archive", wraps=mod.load_archive) as parse:
        recovered = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert parse.call_count == 1, "corrupt contracts must not become hits"
    pd.testing.assert_frame_equal(recovered.daily, first.daily)
    assert len(list(cache.glob("generation-*.duckdb"))) == 1


def test_invalid_source_never_uses_published_generation(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    pointer = (cache / "current.json").read_bytes()
    path = root / "heart_rate/2026-01.csv"
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b",60,", b",61,"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(mod.ArchiveReadError):
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert (cache / "current.json").read_bytes() == pointer


def test_source_change_during_analysis_does_not_publish(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    original = mod.daily_summary

    def changed(*args):
        result = original(*args)
        path = root / "heart_rate/2026-01.csv"
        path.write_bytes(path.read_bytes().replace(b",60,", b",61,"))
        return result

    monkeypatch.setattr(mod, "daily_summary", changed)
    with pytest.raises(mod.ArchiveReadError):
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert not (cache / "current.json").exists()


def test_nullable_object_booleans_keep_scalar_types(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path)
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    hit = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert not first.sleep.is_complete.dropna().empty
    assert [type(v) for v in hit.sleep.is_complete] == [type(v) for v in first.sleep.is_complete]


def test_native_utc_range_is_not_narrowed_by_cache(tmp_path):
    from copy import deepcopy

    from fixture_archive import FIXTURE_DEVICES, FIXTURE_TABLES, FIXTURE_TRACKS

    from healthviz.archive.writer import write_archive

    mod = module()
    _, cache, config = prepare(tmp_path)
    root = tmp_path / "native-range"
    devices = [{**row, "last_seen_utc": "2500-01-01T00:00:00Z"} for row in FIXTURE_DEVICES]
    write_archive(root, deepcopy(FIXTURE_TABLES), devices, FIXTURE_TRACKS, "synthetic")
    expected = load_archive(root)["devices"]
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    hit = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    pd.testing.assert_frame_equal(hit.tables["devices"], expected)


def test_format_change_rebuilds_raw_tables(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    monkeypatch.setattr(mod.store, "FORMAT_VERSION", mod.store.FORMAT_VERSION + 1)
    with patch.object(mod, "load_archive", wraps=mod.load_archive) as parse:
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert parse.call_count == 1


def test_analysis_change_reuses_raw_tables(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    original = mod.fingerprint

    def changed(paths):
        value = original(paths)
        return "analysis-change" if any(p.parent.name == "analysis" for p in paths) else value

    monkeypatch.setattr(mod, "fingerprint", changed)
    with patch.object(mod, "load_archive", side_effect=AssertionError("raw cache was lost")):
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)


def test_empty_archive_and_unicode_round_trip(tmp_path):
    from copy import deepcopy

    from fixture_archive import FIXTURE_DEVICES, FIXTURE_TABLES

    from healthviz.archive.writer import write_archive

    mod = module()
    root, cache, config = prepare(tmp_path)
    root = tmp_path / "empty-archive"
    devices = [{**d, "model": 'Fictional, "quoted"\nUnicode Ω'} for d in FIXTURE_DEVICES]
    write_archive(root, {name: [] for name in deepcopy(FIXTURE_TABLES)}, devices, {}, "synthetic")
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    second = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert second.daily.empty
    for name in first.tables:
        pd.testing.assert_frame_equal(first.tables[name], second.tables[name])


def test_changed_database_during_materialization_cannot_be_a_hit(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    original = mod.store.read_frames
    changed = False

    def damage(path):
        nonlocal changed
        result = original(path)
        if not changed:
            changed = True
            path.write_bytes(b"corrupted after materialization")
        return result

    monkeypatch.setattr(mod.store, "read_frames", damage)
    with patch.object(mod, "load_archive", wraps=mod.load_archive) as parse:
        recovered = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert parse.call_count == 1
    pd.testing.assert_frame_equal(first.daily, recovered.daily)


def test_source_change_during_exclusive_recheck_rejects_hit(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    original = mod.current
    calls = 0

    def changed(directory):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        result = original(directory)
        path = root / "heart_rate/2026-01.csv"
        path.write_bytes(path.read_bytes().replace(b",60,", b",61,"))
        return result

    monkeypatch.setattr(mod, "current", changed)
    with pytest.raises(mod.ArchiveReadError):
        mod.load_read_model(root, Settings(), cache_dir=cache, config=config)


def test_persisted_connection_cannot_write_or_read_external_files(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    path = cache / json.loads((cache / "current.json").read_bytes())["file"]
    with mod.store.connection(path, read_only=True) as conn:
        with pytest.raises(duckdb.Error):
            conn.execute("CREATE TABLE unauthorized AS SELECT 1")
        with pytest.raises(duckdb.Error):
            conn.execute("SELECT * FROM read_csv(?)", [str(root / "devices.csv")])
        with pytest.raises(duckdb.Error):
            conn.execute("INSTALL httpfs")
        assert conn.execute("SELECT current_setting('autoload_known_extensions')").fetchone() == (
            False,
        )


def test_hit_matches_frames_on_a_varied_archive(tmp_path):
    from benchmark_read_model import generate_archive

    mod = module()
    root, cache = tmp_path / "archive", tmp_path / "cache"
    cache.mkdir(mode=0o700)
    # Offsets, a +05:30 trip, gaps, nullable columns, overlapping sources and GPX workouts.
    generate_archive(root, sample_count=12_000)
    config = tmp_path / "config/config.toml"
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    hit = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    for name, frame in load_archive(root).items():
        pd.testing.assert_frame_equal(hit.tables[name], frame)
    for name in ("daily", "sleep", "workouts"):
        pd.testing.assert_frame_equal(getattr(hit, name), getattr(first, name))
