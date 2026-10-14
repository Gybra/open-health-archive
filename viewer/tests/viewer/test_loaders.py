from unittest.mock import patch

import streamlit as st
from dashboard_nav import activity_view, open_page, open_raw_data, show_all, start
from viewer_archive import write_viewer_archive


def test_slow_steps_show_a_timed_loader(tmp_path, monkeypatch):
    shown = []
    original = st.spinner

    def spinner(text="In progress...", **options):
        shown.append((text, options.get("show_time", False)))
        return original(text, **options)

    with patch.object(st, "spinner", spinner):
        app = show_all(
            start(monkeypatch, write_viewer_archive(tmp_path / "a"), tmp_path / "c.toml")
        )
        open_page(app, "Heart")
        open_raw_data(app)
        activity_view(app, "Workouts")
        activity_view(app, "Routes")
    assert not app.exception and not app.error
    texts = {text for text, timed in shown if timed}
    for expected in (
        "Opening the archive…",
        "Loading Overview…",
        "Loading Heart…",
        "Preparing raw data…",
        "Loading Activity…",
        "Loading the workout…",
        "Drawing the map…",
    ):
        assert expected in texts, expected
