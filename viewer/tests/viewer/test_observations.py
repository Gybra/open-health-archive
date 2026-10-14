import importlib
from datetime import date

import pandas as pd


def module():
    assert importlib.util.find_spec("healthviz.analysis.observations"), (
        "baseline observations are missing"
    )
    return importlib.import_module("healthviz.analysis.observations")


def daily(values):
    return pd.DataFrame(
        {
            "date_local": pd.date_range("2026-01-01", periods=len(values)).date,
            "complete": [True] * len(values),
            "resting_hr": values,
            "resting_hr_physical_device_id": ["fictional"] * len(values),
            "resting_hr_computed_by": ["vendor"] * len(values),
            "steps": [None] * len(values),
            "workout_min": [None] * len(values),
            "sleep_min": [None] * len(values),
            "sleep_eligible": [False] * len(values),
        }
    )


def test_baseline_excludes_today_incomplete_and_method_change():
    mod = module()
    frame = daily([50] * 15 + [70])
    args = (pd.DataFrame(), pd.DataFrame(), date(2026, 1, 16))
    messages = mod.observations(frame, *args)
    assert any("50" in s and "70" in s and "15" in s for s in messages)
    frame.loc[15, "complete"] = False
    assert not mod.observations(frame, *args)
    frame.loc[15, "complete"] = True
    frame.loc[15, "resting_hr_computed_by"] = "app"
    assert not mod.observations(frame, *args)
    assert not mod.observations(
        daily([50] * 3 + [70]), pd.DataFrame(), pd.DataFrame(), date(2026, 1, 4)
    )


def test_onset_wraps_midnight():
    mod = module()
    times = pd.Series([23 * 60 + 45, 15])
    assert mod.onset_sd(times) == pd.Series([345, 375]).std()


def test_weekly_reduction_and_records():
    mod = module()
    assert mod.reduced_week(70, [100] * 4) is False
    assert mod.reduced_week(69, [100] * 4) is True
    assert mod.reduced_week(0, [0] * 4) is False
    assert mod.reduced_week(20, [100] * 3) is False


def test_area_observations_partition_messages():
    mod = module()
    frame = daily([50] * 15 + [70])
    as_of = date(2026, 1, 16)
    heart = mod.heart_observations(frame, as_of)
    assert heart
    assert mod.sleep_observations(frame, pd.DataFrame(), as_of) == []
    assert mod.activity_observations(frame, pd.DataFrame(), as_of) == []
    assert mod.observations(frame, pd.DataFrame(), pd.DataFrame(), as_of) == heart
