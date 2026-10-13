import os
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from viewer_archive import write_viewer_archive

import healthviz
from healthviz import read_model
from healthviz.settings import Settings, save_settings


@pytest.fixture(params=[False, True], ids=["memory", "persistent"])
def prepared_app(tmp_path, monkeypatch, request):
    root = write_viewer_archive(tmp_path / "archive")
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o700)
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    argv = [
        "app.py",
        "--archive",
        str(root),
        "--config",
        str(config_dir / "config.toml"),
        "--offline",
    ]
    if request.param:
        argv.extend(["--cache-dir", str(cache)])
    monkeypatch.setattr(sys, "argv", argv)
    path = str(Path(healthviz.__file__).parent / "dashboard/app.py")
    app = AppTest.from_file(path, default_timeout=30).run()
    return app, path, root, config_dir / "config.toml", request.param


def test_new_session_uses_persisted_overview_without_startup_analysis(prepared_app):
    app, path, _, _, persistent = prepared_app
    assert not app.exception and not app.error
    first = app.session_state["snapshot"][2].copy()
    if persistent:
        with (
            patch.object(read_model, "load_archive", side_effect=AssertionError("reparsed")),
            patch.object(read_model, "daily_summary", side_effect=AssertionError("recomputed")),
            patch(
                "healthviz.dashboard.overview.resolve_rows", side_effect=AssertionError("resolved")
            ),
        ):
            second = AppTest.from_file(path, default_timeout=30).run()
    else:
        second = AppTest.from_file(path, default_timeout=30).run()
    assert not second.exception and not second.error
    pd.testing.assert_frame_equal(first, second.session_state["snapshot"][2])


def test_live_snapshot_rejects_same_metadata_corruption(prepared_app):
    app, _, root, _, _ = prepared_app
    assert not app.exception and not app.error
    for key in ("tracks", "resolved_hr", "heatmap"):
        app.session_state[key] = ("old", {})
    path = root / "heart_rate/2026-01.csv"
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b",60,", b",61,"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    app.run()
    assert app.error, "invalid current sources must not display old session frames"
    for key in ("snapshot", "overview_sources", "tracks", "resolved_hr", "heatmap"):
        assert key not in app.session_state
    assert not app.get("plotly_chart")


def test_settings_and_historical_period_remain_dynamic(prepared_app):
    app, _, _, config, _ = prepared_app
    assert not app.exception and not app.error
    save_settings(config, Settings(worn_hours_threshold=11))
    app.run()
    assert not app.exception and not app.error
    daily = app.session_state["snapshot"][2]
    assert not daily.complete.any()
    app.date_input[0].set_value((daily.date_local.min(), daily.date_local.min())).run()
    assert not app.exception and not app.error
    assert len(app.session_state["snapshot"][2]) > 1, "filter must retain full baseline history"
