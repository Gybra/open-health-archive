from datetime import timedelta

import pandas as pd
from area_archive import LAST, write_area_archive
from dashboard_nav import open_page, start

from healthviz.dashboard.charts import coverage_figure, range_figure


def heart_page(tmp_path, monkeypatch):
    root = write_area_archive(tmp_path / "archive")
    return open_page(start(monkeypatch, root, tmp_path / "config.toml"), "Heart")


def metric(app, label):
    return next(m for m in app.metric if m.label == label)


def test_heart_page_key_numbers(tmp_path, monkeypatch):
    app = heart_page(tmp_path, monkeypatch)
    assert not app.exception and not app.error
    resting = metric(app, "Resting heart rate")
    assert (resting.value, resting.delta) == ("55 bpm", "≈ usual")
    assert metric(app, "Average heart rate").value == "70 bpm"
    assert metric(app, "Hours measured per day").value == "12.0 h"
    assert "30 of 30 days measured" in [c.value for c in app.caption]
    assert any(s.value == "Notes" for s in app.subheader)
    assert [e.label for e in app.expander] == ["Raw data and sources"]


def test_heart_page_without_spo2(tmp_path, monkeypatch):
    app = heart_page(tmp_path, monkeypatch)
    assert metric(app, "Blood oxygen").value == "—"
    assert "no readings in this period" in [c.value for c in app.caption]


def days(count):
    return pd.DataFrame(
        {
            "date_local": [LAST - timedelta(days=count - 1 - i) for i in range(count)],
            "hr_min": [50.0] * count,
            "hr_mean": [70.0] * count,
            "hr_max": [150.0] * count,
            "worn_hours": [12] * count,
            "complete": [True] * (count - 1) + [False],
        }
    )


def test_range_figure_shows_band_and_mean_for_complete_days():
    figure = range_figure(days(5), LAST - timedelta(days=4), LAST)
    assert [t.name for t in figure.data] == ["lowest", "highest", "daily average"]
    assert figure.data[1].fill == "tonexty"
    assert list(figure.data[2].y)[-1] != list(figure.data[2].y)[-1]  # incomplete day left out


def test_coverage_figure_marks_complete_day_threshold():
    figure = coverage_figure(days(5), LAST - timedelta(days=4), LAST, 10)
    assert figure.data[0].type == "bar"
    assert list(figure.data[1].y) == [10, 10]
