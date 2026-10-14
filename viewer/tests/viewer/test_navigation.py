from datetime import timedelta

from dashboard_nav import PAGE_NAMES, activity_view, open_page, start
from fixture_archive import FIXTURE_TABLES, fixture_row
from viewer_archive import write_viewer_archive

from healthviz.dashboard.format import day_text
from healthviz.settings import load_settings


def period_caption(app):
    return next(c.value for c in app.caption if " – " in c.value)


def test_sidebar_lists_only_pages(tmp_path, monkeypatch):
    app = start(monkeypatch, write_viewer_archive(tmp_path / "a"), tmp_path / "c.toml")
    # Pages are menu links (st.navigation), not a radio.
    assert [page["page_name"] for page in app._registered_pages.values()] == PAGE_NAMES
    for kind in ("radio", "selectbox", "multiselect", "date_input", "number_input"):
        assert not app.sidebar.get(kind), kind


def test_period_presets_set_range(tmp_path, monkeypatch):
    app = start(monkeypatch, write_viewer_archive(tmp_path / "a"), tmp_path / "c.toml")
    last = app.session_state["snapshot"][2].date_local.max()
    assert app.segmented_control(key="preset").value == "30d"
    assert day_text(last - timedelta(days=29)) + " – " + day_text(last) in period_caption(app)
    app.segmented_control(key="preset").set_value("7d").run()
    assert day_text(last - timedelta(days=6)) + " – " in period_caption(app)
    assert not app.date_input
    app.segmented_control(key="preset").set_value("Custom").run()
    assert app.date_input(key="period").proto.format == "YYYY-MM-DD"


def test_period_persists_across_pages(tmp_path, monkeypatch):
    app = start(monkeypatch, write_viewer_archive(tmp_path / "a"), tmp_path / "c.toml")
    app.segmented_control(key="preset").set_value("7d").run()
    open_page(app, "Settings")
    open_page(app, "Sleep")
    assert app.segmented_control(key="preset").value == "7d"
    assert not app.exception and not app.error


def test_settings_page_saves_profile_and_associations_with_labels(tmp_path, monkeypatch):
    config = tmp_path / "c.toml"
    app = open_page(start(monkeypatch, write_viewer_archive(tmp_path / "a"), config), "Settings")
    origin = next(w for w in app.selectbox if w.label == "Source to associate")
    assert "Fictional · Test watch (synthetic) #2" in origin.options
    origin.set_value("fixture-watch-2")
    next(w for w in app.selectbox if w.label == "Same physical device as").set_value(
        "fixture-watch"
    )
    next(w for w in app.number_input if w.label.startswith("Birth year")).set_value(1990)
    next(b for b in app.button if b.label == "Save private settings").click().run()
    saved = load_settings(config)
    assert saved.device_aliases == {"fixture-watch-2": "fixture-watch"}
    assert saved.birth_year == 1990
    assert not app.exception and not app.error


def duplicate_watch(tmp_path):
    rows = [
        fixture_row(
            "steps",
            record_id=f"{device}-{day}",
            start_utc=f"2026-01-{day:02d}T10:00:00Z",
            end_utc=f"2026-01-{day:02d}T11:00:00Z",
            utc_offset="+01:00",
            count=count,
            device_id=device,
            ingest=ingest,
        )
        for day in (5, 6, 7)
        for device, ingest, count in (
            ("fixture-watch", "xiaomi_export", "8000"),
            ("fixture-watch-2", "health_connect", "8100"),
        )
    ]
    return write_viewer_archive(tmp_path / "a", steps=[*FIXTURE_TABLES["steps"], *rows])


def notices(app):
    return [i.value for i in app.info if "same physical device" in i.value]


def test_duplicate_notice_offers_both_answers(tmp_path, monkeypatch):
    config = tmp_path / "c.toml"
    app = start(monkeypatch, duplicate_watch(tmp_path), config)
    assert notices(app)
    open_page(app, "Settings")
    labels = [b.label for b in app.button]
    assert "Same physical device" in labels and "Not the same device" in labels
    next(b for b in app.button if b.label == "Not the same device").click().run()
    assert load_settings(config).not_same_devices == [["fixture-watch", "fixture-watch-2"]]
    open_page(app, "Overview")
    assert not notices(app)


def test_duplicate_notice_associates_on_request(tmp_path, monkeypatch):
    config = tmp_path / "c.toml"
    app = open_page(start(monkeypatch, duplicate_watch(tmp_path), config), "Settings")
    next(b for b in app.button if b.label == "Same physical device").click().run()
    assert load_settings(config).device_aliases == {"fixture-watch-2": "fixture-watch"}
    assert not app.exception and not app.error


def test_every_page_renders_on_sparse_archive(tmp_path, monkeypatch):
    empty = dict.fromkeys(["sleep_sessions", "sleep_stages", "weight", "spo2", "workouts"], [])
    app = start(monkeypatch, write_viewer_archive(tmp_path / "a", **empty), tmp_path / "c.toml")
    app.segmented_control(key="preset").set_value("All").run()
    for page in PAGE_NAMES:
        open_page(app, page)
        assert not app.exception and not app.error, page
    for view in ("Daily", "Workouts", "Routes"):
        activity_view(app, view)
        assert not app.exception and not app.error, view
    # Without nights or workouts the Day view is still reachable from a daily page.
    open_page(app, "Heart")
    next(b for b in app.button if b.label == "Open day →").click().run()
    assert app.session_state["view"] == "Day"
    assert not app.exception and not app.error


def test_custom_period_waits_for_the_second_date(tmp_path, monkeypatch):
    app = start(monkeypatch, write_viewer_archive(tmp_path / "a"), tmp_path / "c.toml")
    app.segmented_control(key="preset").set_value("Custom").run()
    first = app.session_state["snapshot"][2].date_local.min()
    app.date_input(key="period").set_value((first + timedelta(days=2),)).run()
    assert any(i.value == "Choose the start and end dates." for i in app.info)
    assert app.date_input(key="period").value == (first + timedelta(days=2),)
