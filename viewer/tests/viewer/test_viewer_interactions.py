from datetime import date

import pandas as pd
from streamlit.testing.v1 import AppTest


def test_period_input_is_iso(viewer_app):
    assert viewer_app.date_input[0].proto.format == "YYYY-MM-DD"


def test_day_calorie_kinds_have_separate_traces(viewer_app, tmp_path):
    from fixture_archive import FIXTURE_TABLES
    from viewer_archive import write_viewer_archive

    row = {
        **FIXTURE_TABLES["calories"][-1],
        "record_id": "active-day",
        "kind": "active",
        "kcal": "4",
    }
    write_viewer_archive(tmp_path / "archive", calories=[*FIXTURE_TABLES["calories"], row])
    viewer_app.selectbox(key="page").set_value("Day").run()
    widget = next(w for w in viewer_app.selectbox if w.label == "Day")
    widget.set_value(date(2026, 1, 3)).run()
    import json

    chart = next(
        x
        for x in viewer_app.get("plotly_chart")
        if json.loads(x.proto.spec)["layout"]["title"]["text"] == "Calories"
    )
    assert [row["name"] for row in json.loads(chart.proto.spec)["data"]] == ["active", "total"]


def test_ambiguous_single_source_is_inspectable(viewer_app):
    viewer_app.selectbox(key="page").set_value("Overlaps").run()
    widget = next(w for w in viewer_app.selectbox if w.label == "Metric")
    widget.set_value("workouts").run()
    assert any(
        "ambiguous" in frame.value.get("quality", pd.Series(dtype=str)).tolist()
        for frame in viewer_app.dataframe
    )


def test_priority_metric_updates_before_form_submission(tmp_path):
    # A form delays frontend changes: make the metric selector a separate reactive widget.
    app = AppTest.from_string("""
import pandas as pd
from pathlib import Path
from healthviz.dashboard.app import settings_form
from healthviz.settings import Settings
settings_form(Settings(priority={"heart_rate":["a"],"steps":["b"]}),
    pd.DataFrame({"device_id":["a","b"]}), Path("/tmp/unused-viewer-qa-config"))
""").run()
    widget = next(w for w in app.selectbox if w.label == "Priority metric")
    assert not widget.proto.form_id
    widget.set_value("steps").run()
    assert app.multiselect[0].value == ["b"]


def test_calendar_charts_have_explicit_iso_axes(viewer_app):
    import json

    charts = viewer_app.get("plotly_chart")
    assert len(charts) >= 6
    assert all(
        json.loads(chart.proto.spec)["layout"]["xaxis"].get("tickformat") == "%Y-%m-%d"
        for chart in charts
    )
