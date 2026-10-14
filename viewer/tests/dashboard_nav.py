"""Drive the dashboard's navigation in AppTest sessions."""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

import healthviz

APP = str(Path(healthviz.__file__).parent / "dashboard/app.py")
PAGE_NAMES = ["Overview", "Sleep", "Heart", "Activity", "Body", "Settings"]


def start(monkeypatch, root, config, *extra):
    argv = ["app.py", "--archive", str(root), "--config", str(config), "--offline", *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return AppTest.from_file(APP, default_timeout=60).run()


def open_page(app, page):
    return app.radio(key="page").set_value(page).run()


def show_all(app):
    return app.segmented_control(key="preset").set_value("All").run()


def set_period(app, start, end):
    app.segmented_control(key="preset").set_value("Custom").run()
    return app.date_input(key="period").set_value((start, end)).run()


def activity_view(app, view):
    open_page(app, "Activity")
    return app.segmented_control(key="activity_view").set_value(view).run()


def open_day(app, day):
    app.session_state["view"] = "Day"
    app.session_state["day"] = day
    return app.run()
