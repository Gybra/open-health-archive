import json
from datetime import date

from area_archive import write_area_archive
from dashboard_nav import activity_view, open_day, open_page, start

from healthviz.dashboard.format import day_text


def test_body_page_lists_readings(tmp_path, monkeypatch):
    root = write_area_archive(tmp_path / "archive")
    app = open_page(start(monkeypatch, root, tmp_path / "config.toml"), "Body")
    assert not app.exception and not app.error
    assert next(m for m in app.metric if m.label == "Weight").value == "69.0 kg"
    readings = next(f.value for f in app.dataframe if "Weight" in f.value.columns)
    assert set(readings.Weight) == {"69.0 kg"}
    assert readings.Time.iloc[0] == "07:30"
    assert [e.label for e in app.expander] == ["Raw data and sources"]


def charts(app):
    return [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]


def test_day_view_uses_local_time(viewer_app):
    open_day(viewer_app, date(2026, 1, 3))
    assert not viewer_app.exception and not viewer_app.error
    assert any(s.value == day_text(date(2026, 1, 3)) for s in viewer_app.subheader)
    specs = charts(viewer_app)
    assert specs
    titles = [spec["layout"]["xaxis"].get("title", {}).get("text", "") for spec in specs]
    assert all("UTC" not in title for title in titles)
    heart = next(s for s in specs if s["layout"]["title"]["text"] == "Heart rate")
    assert heart["data"][0]["x"][0].startswith("2026-01-03T01:00")  # 00:00Z at +01:00


def test_day_navigation_buttons(viewer_app):
    open_day(viewer_app, date(2026, 1, 3))
    next(b for b in viewer_app.button if b.label == "Next day ▶").click().run()
    assert any(s.value == day_text(date(2026, 1, 4)) for s in viewer_app.subheader)
    next(b for b in viewer_app.button if b.label == "← Back").click().run()
    assert viewer_app.session_state["view"] is None
    assert not viewer_app.exception and not viewer_app.error


def test_workout_detail_opens_its_day(viewer_app):
    activity_view(viewer_app, "Workouts")
    viewer_app.selectbox(key="workout").set_value(("synthetic", "elevated-walk")).run()
    next(b for b in viewer_app.button if b.label == "Open this day →").click().run()
    assert viewer_app.session_state["view"] == "Day"
    assert any(s.value == day_text(date(2026, 1, 3)) for s in viewer_app.subheader)


def test_back_from_day_restores_the_picked_workout(viewer_app):
    activity_view(viewer_app, "Workouts")
    picked = ("synthetic", "workouts")  # the oldest walk, not the default newest
    viewer_app.selectbox(key="workout").set_value(picked).run()
    next(b for b in viewer_app.button if b.label == "Open this day →").click().run()
    next(b for b in viewer_app.button if b.label == "← Back").click().run()
    assert viewer_app.segmented_control(key="activity_view").value == "Workouts"
    assert viewer_app.selectbox(key="workout").value == picked
    assert not viewer_app.exception and not viewer_app.error


def test_back_from_day_restores_the_picked_night(tmp_path, monkeypatch):
    from datetime import timedelta

    from area_archive import LAST

    root = write_area_archive(tmp_path / "archive")
    app = open_page(start(monkeypatch, root, tmp_path / "config.toml"), "Sleep")
    older = LAST - timedelta(days=5)
    app.selectbox(key="night").set_value(older).run()
    next(b for b in app.button if b.label == "Open this day →").click().run()
    next(b for b in app.button if b.label == "← Back").click().run()
    assert app.selectbox(key="night").value == older
