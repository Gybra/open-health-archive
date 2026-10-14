import json
from unittest.mock import patch

import pandas as pd
import pytest
from test_apps import three_app_archive

from healthviz import read_model as rm
from healthviz.settings import Settings

DERIVED = {"derived_daily", "derived_sleep", "derived_workouts"}
MI = Settings(apps=["Mi Fitness"])


def prepare(tmp_path):
    root = three_app_archive(tmp_path / "archive")
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    config = tmp_path / "config/config.toml"
    return lambda settings: rm.load_read_model(
        root, settings, cache_dir=cache, config=config
    ), cache


def test_apps_change_writes_only_its_results_and_keeps_earlier_ones(tmp_path, monkeypatch):
    load, cache = prepare(tmp_path)
    everything = load(Settings())
    written = []
    original = rm.store.write_frames

    def spy(path, frames, *keys):
        written.append(set(frames))
        return original(path, frames, *keys)

    with (
        patch.object(rm.store, "write_frames", spy),
        patch.object(rm, "load_archive", side_effect=AssertionError("reparsed the archive")),
    ):
        mi = load(MI)
    assert written == [DERIVED]
    assert not mi.daily.equals(everything.daily)
    with patch.object(rm, "derive", side_effect=AssertionError("recomputed")):
        pd.testing.assert_frame_equal(load(Settings()).daily, everything.daily)
        pd.testing.assert_frame_equal(load(MI).daily, mi.daily)
        monkeypatch.setattr(rm, "loaded", {})  # a restarted viewer reads them from disk
        pd.testing.assert_frame_equal(load(MI).daily, mi.daily)
        pd.testing.assert_frame_equal(load(MI).tables["steps"], everything.tables["steps"])


def test_app_order_does_not_change_the_cache_key():
    assert rm.keys("digest", Settings(apps=["B", "A"])) == rm.keys(
        "digest", Settings(apps=["A", "B"])
    )


def test_corrupt_results_are_recomputed(tmp_path, monkeypatch):
    load, cache = prepare(tmp_path)
    load(Settings())
    mi = load(MI)
    [entry] = json.loads((cache / "current.json").read_bytes())["derived"]
    (cache / entry["file"]).write_bytes(b"not a database")
    monkeypatch.setattr(rm, "loaded", {})
    with patch.object(rm, "derive", wraps=rm.derive) as derive:
        pd.testing.assert_frame_equal(load(MI).daily, mi.daily)
    assert derive.call_count == 1


def test_new_data_drops_results_of_the_old_data(tmp_path, monkeypatch):
    load, cache = prepare(tmp_path)
    load(Settings())
    load(MI)
    assert len(list(cache.glob("derived-*.duckdb"))) == 1
    monkeypatch.setattr(rm.store, "FORMAT_VERSION", rm.store.FORMAT_VERSION + 1)
    load(Settings())
    assert not list(cache.glob("derived-*.duckdb"))
    assert not json.loads((cache / "current.json").read_bytes()).get("derived")


@pytest.mark.parametrize("file", ["../config/config.toml", "generation-" + "0" * 32 + ".duckdb"])
def test_tampered_results_entries_are_never_read(tmp_path, monkeypatch, file):
    load, cache = prepare(tmp_path)
    load(Settings())
    load(MI)
    pointer = cache / "current.json"
    state = json.loads(pointer.read_bytes())
    state["derived"][0]["file"] = file
    pointer.write_text(json.dumps(state))
    monkeypatch.setattr(rm, "loaded", {})
    with patch.object(rm, "load_archive", wraps=rm.load_archive) as parse:
        load(MI)
    assert parse.call_count == 1


def test_only_the_latest_results_are_kept(tmp_path, monkeypatch):
    load, cache = prepare(tmp_path)
    monkeypatch.setattr(rm, "MAX_RESULTS", 2)
    load(Settings())
    files = []
    for app in ["Mi Fitness", "Phone (Health Connect)", "Unknown app"]:
        load(Settings(apps=[app]))
        files.append(json.loads((cache / "current.json").read_bytes())["derived"][-1]["file"])
    kept = [e["file"] for e in json.loads((cache / "current.json").read_bytes())["derived"]]
    assert kept == files[1:]
    assert sorted(p.name for p in cache.glob("derived-*")) == sorted(files[1:])
    assert not [k for k in rm.loaded if k[0] == str(cache / files[0])]
