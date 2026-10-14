from datetime import date, timedelta

import pandas as pd

from healthviz.analysis.usual import Comparison
from healthviz.dashboard.charts import clock_figure, daily_figure, stages_figure
from healthviz.dashboard.format import (
    clock_text,
    count_text,
    day_text,
    difference_text,
    measured_text,
    minutes_text,
    pace_text,
)

DAY = date(2026, 10, 13)


def test_readable_values():
    assert day_text(DAY) == "Tue 2026-10-13"
    assert [minutes_text(m) for m in (52, 59.6, 412, 1440)] == [
        "52 min",
        "1 h 00",
        "6 h 52",
        "24 h 00",
    ]
    assert count_text(8410.4) == "8\u202f410"
    assert count_text(950) == "950"
    assert pace_text(5.2) == "5:12 /km"
    assert [clock_text(m) for m in (1428, 1450, 0)] == ["23:48", "00:10", "00:00"]


def test_difference_and_measured_text():
    lower = Comparison(394, 412, 30, 27, 30, True)
    assert difference_text(lower, minutes_text) == "▼ 18 min vs usual"
    assert difference_text(Comparison(8800, 8000, 0, 30, 30, True), count_text) == "▲ 800 vs usual"
    assert difference_text(Comparison(402, 400, 30, 30, 30, True), minutes_text) == "≈ usual"
    assert difference_text(Comparison(400, None, None, 3, 30, False), minutes_text) == (
        "not enough history yet"
    )
    assert difference_text(Comparison(None, 400, 30, 0, 30, True), minutes_text) == ""
    assert measured_text(lower, "nights") == "27 of 30 nights measured"
    readings = Comparison(80.1, 80.5, 0.4, 4, 30, True, DAY)
    assert measured_text(readings, "readings") == "4 days with readings · latest Tue 2026-10-13"
    none = Comparison(None, None, None, 0, 30, False, DAY)
    assert measured_text(none, "readings") == "no readings in this period · latest Tue 2026-10-13"


def daily(values, complete):
    return pd.DataFrame(
        {
            "date_local": [DAY - timedelta(days=len(values) - 1 - i) for i in range(len(values))],
            "steps": values,
            "complete": complete,
            "sleep_eligible": complete,
        }
    )


def test_daily_figure_emphasises_average():
    frame = daily([1000.0] * 9 + [99999.0], [True] * 9 + [False])
    figure = daily_figure(frame, "steps", DAY - timedelta(days=9), DAY, 900.0, "steps")
    names = [trace.name for trace in figure.data]
    assert names == ["single days", "7-day average", "your usual"]
    days, average, usual = figure.data
    assert days.marker.color == "#93b4ef"
    assert (average.line.color, average.line.width) == ("#1f6feb", 2.4)
    assert 99999.0 not in list(days.y) and max(v for v in average.y if v == v) == 1000.0
    assert list(usual.y) == [900.0, 900.0] and usual.line.dash == "dash"
    plain = daily_figure(frame, "steps", DAY - timedelta(days=9), DAY, None, "steps", bars=True)
    assert [trace.type for trace in plain.data] == ["bar", "scatter"]


def nights():
    return pd.DataFrame(
        {
            "date_local": [DAY - timedelta(days=1), DAY],
            "deep_min": [80.0, 70.0],
            "light_min": [240.0, 230.0],
            "rem_min": [90.0, None],
            "awake_min": [20.0, 10.0],
            "onset_wall_min": [1410, 15],
            "wake_wall_min": [420, 400],
        }
    )


def test_stages_figure_stacks_known_stages():
    figure = stages_figure(nights(), 400.0)
    assert figure.layout.barmode == "stack"
    assert [trace.name for trace in figure.data] == ["Deep", "Light", "REM", "Awake", "your usual"]
    assert figure.data[0].marker.color == "#1e40af"
    assert list(figure.data[2].y)[1] != list(figure.data[2].y)[1]  # missing REM stays missing


def test_clock_figure_spans_midnight():
    bars = clock_figure(nights()).data[0]
    assert list(bars.base) == [330, 375]  # minutes after 18:00
    assert list(bars.y) == [450, 385]
