from datetime import timedelta

from area_archive import LAST, PERIOD_START, write_area_archive
from dashboard_nav import start

from healthviz.dashboard.format import count_text, day_text

RAW_MARKERS = ["+00:00", "_utc", "utc_offset", "physical_device_id", "computed_by"]


def overview(tmp_path, monkeypatch, **options):
    root = write_area_archive(tmp_path / "archive", **options)
    return start(monkeypatch, root, tmp_path / "config.toml")


def metric(app, label):
    return next(m for m in app.metric if m.label == label)


def visible_text(app):
    """Everything on the page except the collapsed raw-data section."""
    found = []

    def walk(node):
        if type(node).__name__ == "Expander" and node.label == "Raw data and sources":
            return
        proto = getattr(node, "proto", None)
        if proto is not None:
            found.append(str(proto))
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(app.main)
    return "\n".join(found)


def test_overview_sections_show_usual_comparisons(tmp_path, monkeypatch):
    app = overview(tmp_path, monkeypatch)
    assert not app.exception and not app.error
    steps = metric(app, "Steps per day")
    assert (steps.value, steps.delta) == (count_text(9000), f"▲ {count_text(1000)} vs usual")
    sleep = metric(app, "Asleep per night")
    assert (sleep.value, sleep.delta) == ("6 h 40", "▼ 20 min vs usual")
    assert metric(app, "Resting heart rate").delta == "≈ usual"
    assert metric(app, "Bedtime").value == "23:00"
    assert metric(app, "Weight").value == "69.0 kg"
    captions = [c.value for c in app.caption]
    assert "30 of 30 nights measured" in captions
    assert [e.label for e in app.expander] == ["Raw data and sources"]


def test_banner_lists_changes(tmp_path, monkeypatch):
    app = overview(tmp_path, monkeypatch)
    banner = next(i.value for i in app.info if i.value.startswith("What changed"))
    assert f"Steps per day {count_text(1000)} above your usual" in banner
    assert "Asleep per night 20 min below your usual" in banner
    assert banner.index("Steps") < banner.index("Asleep")


def test_empty_area_shows_last_reading_date(tmp_path, monkeypatch):
    app = overview(tmp_path, monkeypatch, weight_in_period=False)
    assert metric(app, "Weight").value == "—"
    last = LAST - timedelta(days=31)
    assert f"no readings in this period · latest {day_text(last)}" in [c.value for c in app.caption]
    assert not app.exception and not app.error


def test_section_button_opens_detail(tmp_path, monkeypatch):
    app = overview(tmp_path, monkeypatch)
    next(b for b in app.button if b.label == "Sleep details →").click().run()
    assert app.header[0].value == "Sleep"
    assert not app.exception and not app.error


def test_no_utc_or_raw_columns_outside_raw_data(tmp_path, monkeypatch):
    text = visible_text(overview(tmp_path, monkeypatch))
    assert day_text(PERIOD_START) in text
    for marker in RAW_MARKERS:
        assert marker not in text, marker
