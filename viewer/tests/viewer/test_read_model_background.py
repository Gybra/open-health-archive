import json
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from test_apps import three_app_archive

import healthviz
from healthviz import read_model as rm
from healthviz.analysis.apps import app_choices, select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.settings import Settings, save_settings

# Taken at import, before conftest replaces the module attribute for every other test.
start_precompute = getattr(rm, "start_precompute", None)
LABELS = ["Mi Fitness", "Phone (Health Connect)", "Unknown app"]


def prepare(tmp_path):
    root = three_app_archive(tmp_path / "archive")
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    config = tmp_path / "config/config.toml"
    config.parent.mkdir(mode=0o700)

    def load(settings):
        return rm.load_read_model(root, settings, cache_dir=cache, config=config)

    return load, root, cache, config


def prepared(load, settings):
    assert app_choices(load(settings).tables) == LABELS
    with patch.object(rm, "derive", side_effect=AssertionError("not prepared")):
        for apps in rm.app_subsets(LABELS):
            for order in (apps, apps[::-1]):
                load(replace(settings, apps=order))


def test_choices_to_prepare_go_from_single_apps_up_and_are_capped():
    assert rm.app_subsets(["only"]) == [[]]
    assert rm.app_subsets(["b", "a"]) == [[], ["a"], ["b"]]
    three = rm.app_subsets(LABELS)
    assert [len(apps) for apps in three] == [0, 1, 1, 1, 2, 2, 2]
    assert len(rm.app_subsets([str(i) for i in range(6)])) == 63 <= rm.MAX_RESULTS
    assert rm.app_subsets([str(i) for i in range(7)]) == [[], *[[str(i)] for i in range(7)]]


def test_background_prepares_every_app_choice(tmp_path):
    load, root, cache, config = prepare(tmp_path)
    everything = load(Settings())
    rm.precompute(root, cache, config)
    prepared(load, Settings())
    two = load(Settings(apps=["Unknown app", "Mi Fitness"]))
    expected = daily_summary(
        select_apps(everything.tables, ["Mi Fitness", "Unknown app"]),
        everything.tables["devices"],
        Settings(),
    )
    pd.testing.assert_frame_equal(two.daily, expected)


def test_background_keeps_going_when_only_apps_change(tmp_path):
    load, root, cache, config = prepare(tmp_path)
    load(Settings())
    original = rm.derive

    def pick(tables, settings):
        save_settings(config, Settings(apps=["Mi Fitness"]))
        return original(tables, settings)

    with patch.object(rm, "derive", pick):
        rm.precompute(root, cache, config)
    prepared(load, Settings())


def test_background_stops_when_other_settings_change(tmp_path):
    load, root, cache, config = prepare(tmp_path)
    load(Settings())
    original = rm.derive
    calls = []

    def change(tables, settings):
        calls.append(settings)
        save_settings(config, replace(Settings(), worn_hours_threshold=11))
        return original(tables, settings)

    with patch.object(rm, "derive", change):
        rm.precompute(root, cache, config)
    assert len(calls) == 1


def test_background_skips_raw_tables_not_built_for_the_current_data(tmp_path, monkeypatch):
    load, root, cache, config = prepare(tmp_path)
    load(Settings())
    # A valid archive whose raw tables are not the published ones yet, as after an import.
    monkeypatch.setattr(rm.store, "FORMAT_VERSION", rm.store.FORMAT_VERSION + 1)
    calls = []
    with patch.object(rm, "derive", lambda *args: calls.append(args)):
        rm.precompute(root, cache, config)
    assert calls == []


def test_a_newer_run_waits_for_a_stale_one_and_prepares_the_new_settings(tmp_path):
    load, root, cache, config = prepare(tmp_path)
    everything = load(Settings())
    newer = replace(Settings(), worn_hours_threshold=11)
    original = rm.derive
    deriving, release = threading.Event(), threading.Event()

    def stall(tables, settings):
        if settings.worn_hours_threshold != 11:
            deriving.set()
            release.wait(60)
        return original(tables, settings)

    with patch.object(rm, "derive", stall):
        stale = threading.Thread(target=rm.precompute, args=(root, cache, config))
        stale.start()
        assert deriving.wait(60)
        save_settings(config, newer)
        load(newer)
        newest = threading.Thread(target=rm.precompute, args=(root, cache, config))
        newest.start()
        newest.join(2)
        assert newest.is_alive()  # still waiting for the stale run
        release.set()
        stale.join(120)
        newest.join(120)
    prepared(load, newer)
    published = [e["key"] for e in json.loads((cache / "current.json").read_bytes())["derived"]]
    assert rm.keys(everything.content_digest, Settings(apps=["Mi Fitness"]))[1] not in published


@pytest.mark.parametrize("error", [RuntimeError("PRIVATE 187 bpm"), KeyboardInterrupt()])
def test_background_errors_stay_inside_the_run(tmp_path, error):
    load, root, cache, config = prepare(tmp_path)
    load(Settings())
    with patch.object(rm, "derive", side_effect=error):
        rm.precompute(root, cache, config)


def test_a_failing_background_process_prints_nothing(tmp_path, capfd):
    load, root, cache, config = prepare(tmp_path)
    everything = load(Settings())
    config.write_text("edited by hand")
    process = start_precompute(root, cache, config, everything.content_digest, Settings())
    process.join(180)
    assert process.exitcode == 0
    assert capfd.readouterr().err == ""


def test_the_background_process_makes_no_connections(tmp_path):
    missing = str(tmp_path / "missing")
    code = (
        "import socket, sys\n"
        "from pathlib import Path\n"
        "from healthviz import read_model\n"
        "read_model.background(*[Path(sys.argv[1])] * 3)\n"
        "socket.create_connection(('127.0.0.1', 9), timeout=1)\n"
    )
    run = subprocess.run([sys.executable, "-c", code, missing], capture_output=True, text=True)
    assert "outbound connections are disabled" in run.stderr


def test_viewer_starts_one_daemon_run_per_data_and_settings(tmp_path, monkeypatch):
    load, root, cache, config = prepare(tmp_path)
    started = []

    class Process:
        def __init__(self, target, args, daemon):
            started.append((target, args, daemon))

        def start(self):
            pass

    monkeypatch.setattr(
        rm.multiprocessing, "get_context", lambda method: SimpleNamespace(Process=Process)
    )
    start_precompute(root, cache, config, "digest", Settings())
    start_precompute(root, cache, config, "digest", Settings(apps=["Mi Fitness"]))
    start_precompute(root, cache, config, "digest", replace(Settings(), worn_hours_threshold=11))
    start_precompute(root, cache, config, "new data", Settings())
    assert [(target, daemon) for target, _, daemon in started] == [(rm.background, True)] * 3


def test_a_run_that_cannot_start_leaves_the_viewer_working(tmp_path, monkeypatch):
    load, root, cache, config = prepare(tmp_path)

    class Process:
        def __init__(self, target, args, daemon):
            pass

        def start(self):
            raise OSError("no more processes")

    monkeypatch.setattr(
        rm.multiprocessing, "get_context", lambda method: SimpleNamespace(Process=Process)
    )
    assert start_precompute(root, cache, config, "digest", Settings()) is None


def test_dashboard_starts_the_background_run(tmp_path, monkeypatch):
    load, root, cache, config = prepare(tmp_path)
    calls = []
    monkeypatch.setattr(rm, "start_precompute", lambda *args: calls.append(args))
    argv = ["app.py", "--archive", str(root), "--config", str(config), "--offline"]
    monkeypatch.setattr(sys, "argv", [*argv, "--cache-dir", str(cache)])
    app = AppTest.from_file(str(Path(healthviz.__file__).parent / "dashboard/app.py")).run()
    assert not app.exception and not app.error
    assert [args[:3] for args in calls] == [(root, cache, config)]


def test_the_background_process_really_runs(tmp_path):
    load, root, cache, config = prepare(tmp_path)
    everything = load(Settings())
    process = start_precompute(root, cache, config, everything.content_digest, Settings())
    process.join(180)
    assert process.exitcode == 0
    prepared(load, Settings())
