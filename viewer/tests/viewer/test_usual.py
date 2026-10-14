from datetime import date, timedelta

import pandas as pd
import pytest

from healthviz.analysis.usual import (
    Comparison,
    changes,
    compare_daily,
    compare_nights,
    compare_readings,
    compare_weekly_total,
)

START = date(2026, 6, 1)


def daily(values, *, first=START - timedelta(days=90), complete=True, **columns):
    days = [first + timedelta(days=i) for i in range(len(values))]
    frame = pd.DataFrame({"date_local": days, "steps": values, "complete": complete})
    frame["sleep_eligible"] = complete
    for name, column in columns.items():
        frame[name] = column
    return frame


def test_period_mean_against_preceding_90_days():
    frame = daily([1000.0] * 90 + [2000.0] * 10)
    frame.loc[95, "complete"] = False  # incomplete days stay out of the mean
    frame.loc[95, "steps"] = 99999.0
    result = compare_daily(frame, "steps", START, START + timedelta(days=9))
    assert (result.value, result.usual, result.spread) == (2000.0, 1000.0, 0.0)
    assert (result.counted, result.total, result.enough) == (9, 10, True)
    assert result.difference == 1000.0


def test_sleep_uses_eligible_nights_and_20_night_minimum():
    frame = daily([0.0] * 100, sleep_min=[400.0] * 100)
    frame["complete"] = False
    frame["sleep_eligible"] = [i % 5 == 0 for i in range(90)] + [True] * 10
    result = compare_daily(frame, "sleep_min", START, START + timedelta(days=9))
    assert (result.counted, result.usual) == (10, 400.0)
    assert not result.enough  # 18 eligible nights before the period
    frame.loc[:89, "sleep_eligible"] = [i % 4 == 0 for i in range(90)]
    assert compare_daily(frame, "sleep_min", START, START + timedelta(days=9)).enough


def test_short_history_has_no_difference():
    frame = daily([1000.0] * 29 + [2000.0] * 10, first=START - timedelta(days=29))
    result = compare_daily(frame, "steps", START, START + timedelta(days=9))
    assert result.usual == 1000.0 and not result.enough
    assert result.difference is None


def test_no_counted_days_in_period_gives_none():
    frame = daily([1000.0] * 100)
    frame.loc[90:, "complete"] = False
    result = compare_daily(frame, "steps", START, START + timedelta(days=9))
    assert (result.value, result.counted, result.difference) == (None, 0, None)


def test_workout_minutes_are_weekly_totals_with_absent_days_as_zero():
    minutes = [30.0 if i % 7 == 0 else None for i in range(90)] + [60.0, None] * 7
    quality = ["missing" if m is None else "recorded" for m in minutes]
    frame = daily([0.0] * 104, workout_min=minutes, workout_min_quality=quality)
    frame.loc[103, "workout_min_quality"] = "ambiguous"  # unknown, not zero
    result = compare_weekly_total(frame, "workout_min", START, START + timedelta(days=13))
    assert result.value == pytest.approx(420 / 13 * 7)
    assert result.usual == pytest.approx(30 * 13 / 90 * 7)
    assert result.enough and result.spread is not None


def test_readings_ignore_completeness_and_report_latest():
    readings = pd.DataFrame(
        {
            "date_local": [START - timedelta(days=40), START + timedelta(days=2)],
            "value": [80.0, 78.0],
        }
    )
    result = compare_readings(readings, START, START + timedelta(days=9))
    assert (result.value, result.usual, result.counted, result.enough) == (78.0, 80.0, 1, True)
    assert result.latest == START + timedelta(days=2)
    later = compare_readings(readings, START + timedelta(days=10), START + timedelta(days=19))
    assert later.value is None and later.latest == START + timedelta(days=2)


def test_nights_use_main_eligible_sessions_and_unwrap_clock():
    nights = pd.DataFrame(
        {
            "date_local": [START - timedelta(days=i) for i in range(1, 25)]
            + [START, START, START + timedelta(days=1)],
            "main": [True] * 25 + [False, True],
            "eligible": [True] * 26 + [True],
            "onset_wall_min": [1430] * 24 + [10, 600, 20],
        }
    )
    result = compare_nights(nights, "onset_wall_min", START, START + timedelta(days=1), clock=True)
    assert (result.value, result.usual, result.counted) == (1455.0, 1430.0, 2)
    assert result.difference == 25.0


def comparison(value, usual, spread, enough=True):
    return Comparison(value, usual, spread, 10, 10, enough)


def test_changes_pick_largest_relative_differences():
    text = "{:.0f}".format
    found = changes(
        {
            "a": ("Steps", comparison(130, 100, 10), text),
            "b": ("Sleep", comparison(80, 100, 10), text),
            "c": ("Resting heart rate", comparison(106, 100, 10), text),
            "d": ("Weight", comparison(104, 100, 10), text),  # below half a spread
            "e": ("Distance", comparison(200, 100, 10, enough=False), text),
            "f": ("Active energy", comparison(107, 100, 10), text),
        }
    )
    assert found == [
        "Steps 30 above your usual",
        "Sleep 20 below your usual",
        "Active energy 7 above your usual",
    ]
    assert changes({"d": ("Weight", comparison(104, 100, 10), text)}) == [
        "No large changes from your usual"
    ]


def test_latest_counted_day_is_reported():
    frame = daily([1000.0] * 95 + [None] * 5)
    result = compare_daily(frame, "steps", START + timedelta(days=5), START + timedelta(days=9))
    assert result.value is None and result.latest == START + timedelta(days=4)


def test_weekly_workouts_ignore_unworn_days():
    minutes = [60.0 if i % 2 else None for i in range(104)]
    quality = ["missing" if m is None else "recorded" for m in minutes]
    frame = daily([0.0] * 104, workout_min=minutes, workout_min_quality=quality)
    # A drawer fortnight before the period and four unworn days inside it: unknown, not 0.
    frame.loc[60:73, "complete"] = False
    frame.loc[[90, 92, 94, 96], "complete"] = False
    result = compare_weekly_total(frame, "workout_min", START, START + timedelta(days=13))
    assert result.counted == 10
    assert result.value == pytest.approx(7 * 60 * 7 / 10)
    assert result.usual == pytest.approx(30 * 7)
    frame.loc[:65, "complete"] = False
    assert not compare_weekly_total(frame, "workout_min", START, START + timedelta(days=13)).enough
