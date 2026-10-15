import csv
import io
import json
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
from dashboard_nav import open_day, open_page, open_raw_data, start
from resting_archive import FIRST, LAST, write_resting_archive

from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import load_archive
from healthviz.dashboard import charts, format
from healthviz.settings import Settings


@pytest.fixture
def resting_daily(tmp_path):
    tables = load_archive(write_resting_archive(tmp_path / "archive"))
    return daily_summary(tables, tables["devices"], Settings())


def test_resting_chart_distinguishes_methods_without_changing_eligibility(resting_daily):
    assert hasattr(charts, "resting_figure"), "resting HR needs its provenance chart"
    figure = charts.resting_figure(resting_daily, FIRST, LAST, 54)
    provided, estimate, average, usual = figure.data
    assert [t.name for t in figure.data] == [
        "Provided by source",
        "Estimated from sleep",
        "7-day average",
        "your usual",
    ]
    assert figure.layout.legend.yanchor == "bottom", "wrapped legend must stay above the data"
    assert figure.layout.legend.y > 1
    assert provided.marker.symbol != estimate.marker.symbol
    assert provided.mode == estimate.mode == "markers"
    assert list(provided.y[:3]) == [55, 52, None]
    assert estimate.y[2] == 60
    assert all(y is None for y in provided.y[3:])
    assert all(y is None for y in estimate.y[3:])
    assert "Mi Fitness via Health Connect" in provided.text[1]
    assert "historical" not in provided.text[1].lower()
    assert "Estimated by viewer" in estimate.text[2]
    original = charts.daily_figure(resting_daily, "resting_hr", FIRST, LAST, 54, "bpm")
    assert average.to_json() == original.data[1].to_json()
    assert usual.to_json() == original.data[2].to_json()
    assert average.connectgaps is False


def test_provided_app_computation_is_not_a_viewer_estimate(resting_daily):
    assert hasattr(charts, "resting_figure")
    resting_daily.loc[0, "resting_hr_computed_by"] = "app"
    figure = charts.resting_figure(resting_daily, FIRST, LAST, None)
    assert figure.data[0].y[0] == 55
    assert figure.data[1].y[0] is None


def test_empty_and_unavailable_resting_charts_have_no_invented_points(resting_daily):
    assert hasattr(charts, "resting_figure")
    empty = charts.resting_figure(resting_daily.iloc[:0], FIRST, LAST, None)
    assert not empty.data
    missing = resting_daily.loc[
        resting_daily.date_local.between(date(2026, 1, 4), date(2026, 1, 9))
    ]
    figure = charts.resting_figure(missing, FIRST, LAST, None)
    assert all(v is None for trace in figure.data[:2] for v in trace.y)


def test_resting_hover_escapes_untrusted_source_text(resting_daily):
    assert hasattr(charts, "resting_figure")
    resting_daily.loc[0, "resting_hr_source_app"] = '<a href="https://example.invalid">app</a>'
    text = charts.resting_figure(resting_daily, FIRST, LAST, None).data[0].text[0]
    assert "<a" not in text
    assert "&lt;a" in text


@pytest.mark.parametrize("page", ["Heart", "Overview"])
def test_resting_pages_show_methods_and_explain_gaps(tmp_path, monkeypatch, page):
    root = write_resting_archive(tmp_path / "archive")
    app = start(monkeypatch, root, tmp_path / "config.toml")
    if page == "Heart":
        open_page(app, page)
    assert not app.exception and not app.error
    specs = [json.loads(c.proto.spec) for c in app.get("plotly_chart")]
    assert any(s["data"][0].get("name") == "Provided by source" for s in specs)
    captions = "\n".join(c.value for c in app.caption)
    assert "sufficient heart-rate samples during main sleep" in captions
    assert "6 days unavailable" in captions
    assert "1 recorded day excluded" in captions
    assert "methods may differ" in captions
    if page == "Heart":
        open_raw_data(app)
        frame = next(f.value for f in app.dataframe if "resting_hr_ingest" in f.value)
        assert frame.loc[1, "resting_hr_ingest"] == "health_connect"
        assert (
            frame.loc[3, "resting_hr_quality"] == "missing: no heart rate samples during main sleep"
        )
        assert any(b.proto.url for b in app.get("download_button"))


@pytest.mark.parametrize(
    "day,expected",
    [
        (2, "Provided by source · Mi Fitness via Health Connect"),
        (3, "Estimated by viewer from main sleep"),
        (4, "Unavailable · no heart rate samples during main sleep"),
        (10, "excluded from daily aggregates: incomplete daily coverage"),
    ],
)
def test_day_view_explains_the_selected_resting_value(tmp_path, monkeypatch, day, expected):
    root = write_resting_archive(tmp_path / "archive")
    app = start(monkeypatch, root, tmp_path / "config.toml")
    open_day(app, date(2026, 1, day))
    assert not app.exception and not app.error
    assert any(expected in text.value for text in app.text)
    if day == 10:
        assert next(m for m in app.metric if m.label == "Resting heart rate").value == "52 bpm"
        assert not any("Unavailable" in text.value for text in app.text)


def test_resting_csv_preserves_provenance_and_missing_reasons(resting_daily):
    with patch.object(charts.st, "download_button") as download:
        charts.summary_table(resting_daily, "Daily heart values")
    rows = list(csv.DictReader(io.StringIO(download.call_args.args[1].decode())))
    assert rows[1]["resting_hr_ingest"] == "health_connect"
    assert rows[1]["resting_hr_source_app"] == "com.xiaomi.wearable"
    assert rows[2]["resting_hr"] == "60.0"
    assert rows[3]["resting_hr"] == ""
    assert rows[3]["resting_hr_quality"] == "missing: no heart rate samples during main sleep"


def test_resting_text_preserves_the_recorded_missing_reason(resting_daily):
    assert hasattr(format, "resting_text")
    for row in resting_daily.itertuples():
        if pd.isna(row.resting_hr):
            assert format.resting_text(
                row
            ) == "Unavailable · " + row.resting_hr_quality.removeprefix("missing: ")
