import json

from area_archive import write_area_archive
from dashboard_nav import activity_view, open_page, start

from healthviz.dashboard.format import count_text


def workouts_list(app):
    return next(frame.value for frame in app.dataframe if "Pace" in frame.value.columns)


def test_activity_key_numbers_and_daily_view(tmp_path, monkeypatch):
    root = write_area_archive(tmp_path / "archive")
    app = open_page(start(monkeypatch, root, tmp_path / "config.toml"), "Activity")
    assert not app.exception and not app.error
    steps = next(m for m in app.metric if m.label == "Steps per day")
    assert (steps.value, steps.delta) == (count_text(9000), f"▲ {count_text(1000)} vs usual")
    assert [t.label for t in app.tabs] == ["Steps", "Distance", "Active energy", "Total energy"]
    assert any("never added" in c.value for c in app.caption)
    assert [e.label for e in app.expander] == ["Raw data and sources"]


def test_activity_lists_workouts_readably(viewer_app):
    activity_view(viewer_app, "Workouts")
    assert not viewer_app.exception and not viewer_app.error
    frame = workouts_list(viewer_app).set_index("Start")
    assert frame.loc["03:00", "Pace"] == "15:00 /km"
    assert frame.loc["03:00", "Type"] == "Walking"
    assert frame.loc["03:00", "Duration"] == "30 min"
    assert "Strength training" in set(frame.Type)
    assert not [c for c in frame.columns if "utc" in c.lower() or "_id" in c]
    assert not frame.isna().any().any()


def test_workout_selection_opens_detail(viewer_app):
    activity_view(viewer_app, "Workouts")
    viewer_app.selectbox(key="workout").set_value(("synthetic", "elevated-walk")).run()
    assert not viewer_app.exception and not viewer_app.error
    assert any(s.value == "Walking · Sat 2026-01-03 03:00–03:30" for s in viewer_app.subheader)
    pace = next(m for m in viewer_app.metric if m.label == "Pace")
    assert pace.value == "15:00 /km"
    assert any("attribution: vendor" in c.value for c in viewer_app.caption)


def test_routes_view_stays_offline(viewer_app):
    activity_view(viewer_app, "Routes")
    assert not viewer_app.exception and not viewer_app.error
    decks = viewer_app.get("deck_gl_json_chart")
    assert decks and all("http" not in json.dumps(json.loads(d.proto.json)) for d in decks)
