import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from dashboard_nav import open_page
from fixture_archive import fixture_row
from streamlit.testing.v1 import AppTest
from viewer_archive import write_viewer_archive

import healthviz
from healthviz.analysis.apps import app_choices, app_label, select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import load_archive
from healthviz.dashboard.format import literal
from healthviz.read_model import load_read_model
from healthviz.settings import Settings, load_settings

PHONE = "com.android.healthconnect.phone.0123abcd"


def steps(record, app, ingest, count, hour):
    return fixture_row(
        "steps",
        start_utc=f"2026-01-03T{hour:02}:00:00Z",
        end_utc=f"2026-01-03T{hour:02}:30:00Z",
        utc_offset="+01:00",
        count=str(count),
        source_app=app,
        ingest=ingest,
        record_id=record,
    )


def three_app_archive(root):
    return write_viewer_archive(
        root,
        steps=[
            steps("xm", "com.mi.health", "xiaomi_export", 100, 8),
            steps("hc", "com.xiaomi.wearable", "health_connect", 200, 10),
            {**steps("ph", PHONE, "health_connect", 7, 12), "device_id": "fixture-phone"},
        ],
    )


def test_app_labels():
    assert app_label("com.mi.health") == app_label("com.xiaomi.wearable") == "Mi Fitness"
    assert app_label("com.hihonor.health") == "Honor Health"
    assert app_label(PHONE) == "Phone (Health Connect)"
    assert app_label("") == app_label(None) == "Unknown app"
    assert app_label("org.example.tracker") == "org.example.tracker"


def test_mi_fitness_groups_both_ingests(tmp_path):
    tables = load_archive(three_app_archive(tmp_path / "archive"))

    chosen = select_apps(tables, ["Mi Fitness"])

    assert set(chosen["steps"].source_app) == {"com.mi.health", "com.xiaomi.wearable"}
    assert chosen["devices"] is tables["devices"]
    assert "Phone (Health Connect)" in app_choices(tables)


def test_empty_selection_means_all(tmp_path):
    tables = load_archive(three_app_archive(tmp_path / "archive"))

    assert len(select_apps(tables, [])["steps"]) == 3


def test_absent_labels_mean_all(tmp_path):
    tables = load_archive(three_app_archive(tmp_path / "archive"))

    assert len(select_apps(tables, ["Gone App"])["steps"]) == 3


def test_settings_apps_round_trip(tmp_path):
    from healthviz.settings import SettingsError, save_settings

    path = tmp_path / "config.toml"
    save_settings(path, Settings(apps=["Mi Fitness", "Honor Health"], priority={"steps": ["a"]}))
    assert load_settings(path).apps == ["Mi Fitness", "Honor Health"]
    for bad in ([""], ["A", "A"], "Mi Fitness"):
        with pytest.raises(SettingsError):
            save_settings(path, Settings(apps=bad))


def test_filtered_read_model_matches_direct_summary(tmp_path):
    root = three_app_archive(tmp_path / "archive")
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    config = tmp_path / "config/config.toml"
    everything = load_read_model(root, Settings(), cache_dir=cache, config=config)

    mi = load_read_model(root, Settings(apps=["Mi Fitness"]), cache_dir=cache, config=config)

    expected = daily_summary(
        select_apps(everything.tables, ["Mi Fitness"]), everything.tables["devices"], Settings()
    )
    pd.testing.assert_frame_equal(mi.daily, expected)
    assert not mi.daily.equals(everything.daily)
    again = load_read_model(root, Settings(), cache_dir=cache, config=config)
    pd.testing.assert_frame_equal(again.daily, everything.daily)


def viewer(tmp_path, monkeypatch, status=None):
    app = Path(healthviz.__file__).parent / "dashboard/app.py"
    root = three_app_archive(tmp_path / "archive")
    config = tmp_path / "config/config.toml"
    config.parent.mkdir()
    if status is not None:
        (config.parent / "health-connect-import.json").write_text(json.dumps(status))
    argv = ["app.py", "--archive", str(root), "--config", str(config), "--offline"]
    monkeypatch.setattr(sys, "argv", argv)
    return AppTest.from_file(str(app), default_timeout=30).run(), config


def day_steps(app):
    daily = app.session_state["snapshot"][2].set_index("date_local")
    return daily.loc[pd.Timestamp("2026-01-03").date(), "steps"]


def test_sidebar_app_filter_changes_totals(tmp_path, monkeypatch):
    app, config = viewer(tmp_path, monkeypatch)
    widget = next(w for w in app.multiselect if w.label == "Apps")
    assert sorted(widget.value) == sorted(widget.options)
    everything = day_steps(app)

    widget.set_value(["Mi Fitness"]).run()

    assert load_settings(config).apps == ["Mi Fitness"]
    assert day_steps(app) != everything
    assert not app.exception


def test_settings_page_shows_import_status(tmp_path, monkeypatch):
    status = dict(
        folder="~/Downloads",
        zip_name="Health Connect.zip",
        imported_at="2026-10-14T08:00:00Z",
        error="unsupported Health Connect export format",
        format_version=27,
        format_tested=False,
        not_imported={"elevation_gained": 204},
        last_success={"zip_name": "Old.zip", "imported_at": "2026-10-13T08:00:00Z"},
    )

    app, _ = viewer(tmp_path, monkeypatch, status)
    assert any("import failed (see Settings)" in c.value for c in app.caption)

    open_page(app, "Settings")
    texts = " ".join(
        str(e.value) for kind in ("error", "warning", "caption") for e in app.get(kind)
    )
    # Archive and status text is Markdown-escaped; the browser shows it unchanged.
    assert literal("unsupported Health Connect export format") in texts
    assert literal("Old.zip") in texts
    assert "format 27 not yet tested" in texts
    assert "elevation gained: 204" in texts
    assert literal("~/Downloads") in texts
