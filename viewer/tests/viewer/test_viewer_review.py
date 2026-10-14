from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from dashboard_nav import activity_view, show_all
from fixture_archive import FIXTURE_TABLES, fixture_row
from streamlit.testing.v1 import AppTest
from viewer_archive import write_viewer_archive

from healthviz.analysis.daily import daily_summary, period_summary
from healthviz.analysis.gps import map_deck, route_profile
from healthviz.analysis.observations import observations
from healthviz.archive.reader import ArchiveReadError, archive_token, load_archive
from healthviz.dashboard.charts import trend
from healthviz.settings import Settings


def daily(root):
    tables = load_archive(root)
    return tables, daily_summary(tables, tables["devices"], Settings())


def test_active_total_are_not_ambiguous(tmp_path):
    rows = [
        fixture_row(
            "calories",
            record_id=kind,
            kind=kind,
            kcal=value,
            start_utc="2026-01-03T02:00:00Z",
            end_utc="2026-01-03T02:01:00Z",
            utc_offset="+01:00",
        )
        for kind, value in [("active", "10"), ("total", "20")]
    ]
    _, frame = daily(write_viewer_archive(tmp_path, calories=rows))
    row = frame.set_index("date_local").loc[date(2026, 1, 3)]
    assert row.active_kcal == 10
    assert row.total_kcal == 20
    assert row.active_kcal_quality == "observed"


def points(timed=True):
    return pd.DataFrame(
        {
            "segment": [0, 0],
            "lat": [0.0, 0.0],
            "lon": [0.0, 0.001],
            "time": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"] if timed else [None, None],
                utc=True,
            ),
            "elevation_m": [None, None],
        }
    )


def test_sparse_gpx_pace_interpolates_current_endpoint():
    profile = route_profile(points(), pd.DataFrame())
    assert profile.pace_min_km.iloc[-1] == pytest.approx(8.9932, abs=0.001)


def test_untimed_gpx_retains_geometric_route():
    profile = route_profile(points(False), pd.DataFrame())
    assert profile.route_segment.nunique() == 1
    assert profile.pace_min_km.isna().all()
    deck = map_deck(profile, offline=True, coloring="pace")
    assert len(deck.layers[0].data) == 1


@pytest.mark.parametrize("view", ["Daily", "Routes"])
def test_empty_workouts_render_missing_state(viewer_app, tmp_path, view):
    import sys
    from pathlib import Path

    import healthviz

    root = write_viewer_archive(tmp_path / "empty-workouts", workouts=[])
    old = sys.argv
    try:
        sys.argv = [
            "app.py",
            "--archive",
            str(root),
            "--config",
            str(tmp_path / "empty-config.toml"),
            "--offline",
        ]
        app = AppTest.from_file(
            str(Path(healthviz.__file__).parent / "dashboard/app.py"), default_timeout=30
        ).run()
        show_all(app)
        activity_view(app, view)
        assert not app.error
    finally:
        sys.argv = old


def test_overnight_workout_minutes_and_record_eligibility(tmp_path):
    row = fixture_row(
        "workouts",
        workout_id="overnight",
        record_id="overnight",
        type="walking",
        start_utc="2026-01-03T22:30:00Z",
        end_utc="2026-01-03T23:30:00Z",
        utc_offset="+01:00",
        duration_s="3600",
        distance_m="9000",
    )
    tables, frame = daily(write_viewer_archive(tmp_path, workouts=[row]))
    indexed = frame.set_index("date_local")
    assert indexed.loc[date(2026, 1, 3), "workout_min"] == 30
    assert indexed.loc[date(2026, 1, 4), "workout_min"] == 30
    from healthviz.analysis.sources import resolve_rows

    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], Settings())
    assert not any(
        "longest recorded" in s
        for s in observations(frame, pd.DataFrame(), workouts, date(2026, 1, 4))
    )


def baseline(days=63):
    return pd.DataFrame(
        {
            "date_local": pd.date_range("2026-01-05", periods=days).date,
            "complete": [True] * days,
            "sleep_eligible": [True] * days,
            "resting_hr": [None] * days,
            "steps": [100] * days,
            "workout_min": [None] * days,
            "sleep_min": [480] * days,
            "steps_physical_device_id": ["a"] * days,
            "steps_computed_by": ["device"] * days,
            "sleep_min_physical_device_id": ["a"] * days,
            "sleep_min_computed_by": ["vendor"] * days,
        }
    )


def test_period_metric_completeness_requires_values_every_day():
    frame = baseline(7)
    frame["steps"] = [100, None, None, None, None, None, None]
    for metric in [
        "distance",
        "active_kcal",
        "total_kcal",
        "hr_mean",
        "hr_min",
        "hr_max",
        "weight",
        "spo2",
    ]:
        frame[metric] = None
    row = period_summary(frame, "week").iloc[0]
    assert row.steps == 100
    assert row.steps_covered_days == 1
    assert not row.steps_complete


def test_source_change_blocks_movement_and_sleep_comparisons():
    frame = baseline()
    frame.loc[56:, "steps"] = 10
    frame.loc[56:, "steps_physical_device_id"] = "b"
    frame.loc[56:, "sleep_min"] = 420
    frame.loc[56:, "sleep_min_computed_by"] = "device"
    sleep = pd.DataFrame(
        {
            "date_local": frame.date_local,
            "main": [True] * 63,
            "eligible": [True] * 63,
            "sleep_min": frame.sleep_min,
            "onset_wall_min": [1380] * 63,
        }
    )
    messages = observations(frame, sleep, pd.DataFrame(), date(2026, 3, 9))
    assert not any("below 70%" in s or "differs by" in s for s in messages)


def test_selector_uses_composite_record_identity():
    import healthviz.dashboard.charts as charts

    assert hasattr(charts, "select_record"), "composite detail selection is missing"
    app = AppTest.from_string("""
import pandas as pd
import streamlit as st
from healthviz.dashboard.charts import select_record
frame=pd.DataFrame([
    {'device_id':'a','ingest':ingest,'record_id':record,'workout_id':'same',
     'type':'walking','date_local':'2026-01-01',
     'start_utc':pd.Timestamp('2026-01-01',tz='UTC'),'utc_offset':'+01:00'}
    for ingest,record in [('vendor','one'),('health_connect','two')]
])
st.write(select_record(frame,'Workout')['record_id'])
""").run()
    app.selectbox[0].select_index(1).run()
    assert app.markdown[-1].value == "two"


def test_track_change_after_snapshot_fails_closed(tmp_path, monkeypatch):
    from healthviz.dashboard import workouts as mod

    root = write_viewer_archive(tmp_path)
    token = archive_token(root)
    monkeypatch.setattr(
        mod,
        "st",
        SimpleNamespace(session_state={"snapshot": ((token, Settings()), {}, pd.DataFrame())}),
    )
    path = root / "tracks/walk.gpx"
    path.write_bytes(path.read_bytes().replace(b"0.003", b"0.004"))
    with pytest.raises(ArchiveReadError):
        mod.cached_tracks(root, {"tracks/walk.gpx"})


def test_missing_ascent_attribution_does_not_break_detail(viewer_app, tmp_path):
    import sys
    from pathlib import Path

    import healthviz

    workouts = [{**FIXTURE_TABLES["workouts"][-1], "ascent_computed_by": ""}]
    root = write_viewer_archive(tmp_path / "attribution", workouts=workouts)
    old = sys.argv
    try:
        sys.argv = [
            "app.py",
            "--archive",
            str(root),
            "--config",
            str(tmp_path / "attribution.toml"),
            "--offline",
        ]
        app = AppTest.from_file(
            str(Path(healthviz.__file__).parent / "dashboard/app.py"), default_timeout=30
        ).run()
        show_all(app)
        activity_view(app, "Workouts")
        assert not app.error
        assert any("attribution: unknown" in caption.value for caption in app.caption)
    finally:
        sys.argv = old


def test_rolling_means_keep_history_outside_viewport():
    dates = pd.date_range("2026-01-01", periods=8).date
    frame = pd.DataFrame({"date_local": dates, "steps": [100] * 8, "complete": [True] * 8})
    figure = trend(frame, "steps", "Steps", "count", start=date(2026, 1, 8), end=date(2026, 1, 8))
    assert figure.data[2].y[0] == 100
    assert len(figure.data[0].x) == 1


def test_route_and_download_share_validated_original_bytes(tmp_path, monkeypatch):
    from healthviz.dashboard import workouts as mod

    root = write_viewer_archive(tmp_path)
    original = (root / "tracks/walk.gpx").read_bytes()
    token = archive_token(root)
    state = {"snapshot": ((token, Settings()), {}, pd.DataFrame())}
    monkeypatch.setattr(mod, "st", SimpleNamespace(session_state=state))
    points = mod.cached_tracks(root, {"tracks/walk.gpx"})
    assert len(points["tracks/walk.gpx"]) == 3
    assert state["tracks"][1]["tracks/walk.gpx"][1] == original
