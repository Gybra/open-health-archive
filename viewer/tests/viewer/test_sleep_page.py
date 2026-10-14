from datetime import timedelta

from area_archive import LAST, write_area_archive
from dashboard_nav import open_page, start

from healthviz.dashboard.format import day_text


def sleep_page(tmp_path, monkeypatch, **options):
    root = write_area_archive(tmp_path / "archive", **options)
    return open_page(start(monkeypatch, root, tmp_path / "config.toml"), "Sleep")


def nights_list(app):
    return next(frame.value for frame in app.dataframe if "Night" in frame.value.columns)


def test_sleep_page_lists_nights_in_local_time(tmp_path, monkeypatch):
    app = sleep_page(tmp_path, monkeypatch, utc_offset="+02:00")
    assert not app.exception and not app.error
    per_night = next(m for m in app.metric if m.label == "Per night")
    assert (per_night.value, per_night.delta) == ("6 h 40", "▼ 20 min vs usual")
    assert next(m for m in app.metric if m.label == "Nights measured").value == "30 / 30"
    frame = nights_list(app)
    latest = frame.iloc[0]
    assert latest["Night"] == day_text(LAST)
    assert latest["From → to"] == "01:00 → 09:00"
    assert not [c for c in frame.columns if "utc" in c.lower() or "_id" in c]
    assert list(frame.columns)[:3] == ["Night", "Asleep", "From → to"]
    assert not frame.isna().any().any()
    assert [e.label for e in app.expander] == ["Raw data and sources"]


def test_selected_night_follows_period(tmp_path, monkeypatch):
    app = sleep_page(tmp_path, monkeypatch)
    older = LAST - timedelta(days=20)
    app.selectbox(key="night").set_value(older).run()
    assert any(day_text(older) in s.value for s in app.subheader)
    app.segmented_control(key="preset").set_value("7d").run()
    assert app.selectbox(key="night").value == LAST
    assert not app.exception and not app.error


def test_nights_without_stages_say_so(tmp_path, monkeypatch):
    app = sleep_page(tmp_path, monkeypatch)
    assert any("No stage timeline" in i.value for i in app.info)


def test_sleep_notes_show_observations(tmp_path, monkeypatch):
    app = sleep_page(tmp_path, monkeypatch)
    assert any(s.value == "Notes" for s in app.subheader)
    assert any("Sleep onset SD" in t.value for t in app.text)


def test_missing_nights_are_blank_rows_after_the_measured_columns():
    import pandas as pd

    from healthviz.dashboard.sleep import nights_list

    night = {
        "date_local": LAST,
        "sleep_min": 400.0,
        "onset_wall_min": 1380,
        "wake_wall_min": 420,
        "deep_min": 90.0,
        "device_id": "watch",
        "eligible": True,
    }
    frame = nights_list(pd.DataFrame([night]), LAST - timedelta(days=1), LAST, {"watch": "Watch"})
    assert list(frame.columns)[:3] == ["Night", "Asleep", "From → to"]
    assert list(frame["Note"]) == ["", "not measured"]
    assert not frame.isna().any().any()
