import json
from copy import deepcopy
from datetime import date

from dashboard_nav import PAGE_NAMES, activity_view, open_day, open_page, show_all, start
from fixture_archive import FIXTURE_DEVICES, FIXTURE_TABLES, FIXTURE_TRACKS, fixture_row

from healthviz.archive.writer import write_archive

# Lower case: type labels capitalise only the first character, which is "!".
MARKER = "![private-sentinel](https://example.invalid/image.png)"
MARKDOWN_KINDS = (
    "markdown",
    "caption",
    "title",
    "header",
    "subheader",
    "info",
    "warning",
    "error",
    "success",
    "metric",
)


def hostile_archive(root):
    """Archive text an app could write through Health Connect: workout type, device names."""
    tables = deepcopy(FIXTURE_TABLES)
    tables["workouts"] = [{**row, "type": MARKER} for row in tables["workouts"]]
    tables["steps"] += [
        fixture_row(
            "steps",
            record_id=f"{device}-{day}",
            start_utc=f"2026-01-{day:02d}T10:00:00Z",
            end_utc=f"2026-01-{day:02d}T11:00:00Z",
            utc_offset="+01:00",
            count="8000",
            device_id=device,
            ingest=ingest,
        )
        for day in (5, 6, 7)
        for device, ingest in (
            ("fixture-watch", "xiaomi_export"),
            ("fixture-watch-2", "health_connect"),
        )
    ]
    devices = deepcopy(FIXTURE_DEVICES)
    for device in devices:
        device.update(model=MARKER, vendor=MARKER)
    write_archive(root, tables, devices, FIXTURE_TRACKS, "synthetic hostile")
    return root


def leaks(app):
    found = []
    for kind in MARKDOWN_KINDS:
        for element in app.get(kind):
            if MARKER in str(element.proto):
                found.append(kind)
    return found


def test_archive_text_never_renders_as_markdown(tmp_path, monkeypatch):
    status = tmp_path / "health-connect-import.json"
    status.write_text(
        json.dumps(
            {
                "folder": MARKER,
                "zip_name": MARKER,
                "imported_at": "2026-01-01T00:00:00Z",
                "error": MARKER,
                "last_success": {"zip_name": MARKER},
            }
        )
    )
    app = show_all(start(monkeypatch, hostile_archive(tmp_path / "a"), tmp_path / "config.toml"))
    assert not leaks(app), "overview"
    for page in PAGE_NAMES:
        open_page(app, page)
        assert not app.exception and not leaks(app), page
    for view in ("Routes", "Workouts"):
        activity_view(app, view)
        assert not leaks(app), view
    app.selectbox(key="workout").set_value(("synthetic", "elevated-walk")).run()
    assert not leaks(app), "workout detail"
    open_day(app, date(2026, 1, 3))
    assert not app.exception and not leaks(app), "day"
