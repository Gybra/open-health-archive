import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd

from healthviz.analysis.sources import resolve_rows
from healthviz.settings import Settings

NS = "datetime64[ns]"


def by_time(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Row positions in time order and their sorted UTC times, as numbers that search fast."""
    times = frame.time_utc.to_numpy(NS)
    order = np.argsort(times, kind="stable")
    return order, times[order]


def workout_heart_rate(
    rows: pd.DataFrame, workouts: pd.DataFrame, devices: pd.DataFrame, settings: Settings
) -> pd.DataFrame:
    """Resolved heart rate inside workouts, without resolving the whole archive.

    Sources compete per local hour, so every sample that competes with one inside a workout
    lies within an hour of it; the samples inside get the same winner as a full resolution.
    """
    margin = pd.Timedelta(hours=1)
    order, times = by_time(rows)
    starts = np.searchsorted(times, (workouts.start_utc - margin).to_numpy(NS), side="left")
    ends = np.searchsorted(times, (workouts.end_utc + margin).to_numpy(NS), side="right")
    depth = np.zeros(len(rows) + 1, dtype=int)
    np.add.at(depth, starts, 1)
    np.add.at(depth, ends, -1)
    keep = order[np.cumsum(depth)[:-1] > 0]
    return resolve_rows("heart_rate", rows.iloc[np.sort(keep)], devices, settings)[0]


def max_hr(
    settings: Settings, hr: pd.DataFrame, workouts: pd.DataFrame, as_of: date
) -> tuple[float | None, str]:
    if settings.max_hr is not None:
        return settings.max_hr, "configured"
    start = as_of.replace(
        year=as_of.year - 1, day=min(as_of.day, calendar.monthrange(as_of.year - 1, as_of.month)[1])
    )
    lower, upper = pd.Timestamp(start, tz="UTC"), pd.Timestamp(as_of + timedelta(days=1), tz="UTC")
    peaks = []
    if not hr.empty and not workouts.empty:
        order, times = by_time(hr)
        for workout in workouts.itertuples():
            first, last = np.searchsorted(
                times,
                [
                    max(lower, workout.start_utc).to_datetime64(),
                    min(upper, workout.end_utc).to_datetime64(),
                ],
            )
            # Rows in archive order, as the previous boolean filter returned them.
            samples = hr.iloc[np.sort(order[first:last])].sort_values("time_utc")
            bpm = samples.bpm
            confirmed = (
                (bpm - bpm.shift()).abs().le(10)
                & (bpm - bpm.shift(-1)).abs().le(10)
                & samples.time_utc.diff().dt.total_seconds().le(120)
                & (samples.time_utc.shift(-1) - samples.time_utc).dt.total_seconds().le(120)
            )
            values = bpm.loc[confirmed]
            if not values.empty:
                peaks.append(float(values.max()))
    if peaks:
        return max(peaks), "observed"
    if settings.birth_year is not None:
        return 208 - 0.7 * (as_of.year - settings.birth_year), "age_formula"
    return None, "unavailable"


def zone_seconds(hr: pd.DataFrame, start, end, maximum: float | None) -> pd.DataFrame:
    if maximum is None or hr.empty:
        return pd.DataFrame(columns=["zone", "seconds"])
    samples = hr.loc[(hr.time_utc >= start) & (hr.time_utc < end)].sort_values("time_utc").copy()
    duration = (
        (samples.time_utc.shift(-1).clip(upper=end) - samples.time_utc)
        .dt.total_seconds()
        .clip(upper=120)
        .fillna(0)
    )
    percentage = samples.bpm / maximum * 100
    zones = {
        "below Z1": percentage < 50,
        "Z1": percentage.between(50, 60, inclusive="left"),
        "Z2": percentage.between(60, 70, inclusive="left"),
        "Z3": percentage.between(70, 80, inclusive="left"),
        "Z4": percentage.between(80, 90, inclusive="left"),
        "Z5": percentage.between(90, 100, inclusive="both"),
        "above max": percentage > 100,
    }
    return pd.DataFrame(
        [{"zone": zone, "seconds": duration.loc[mask].sum()} for zone, mask in zones.items()]
    )


def resting_from_sleep(hr: pd.DataFrame, sleep: pd.DataFrame) -> pd.DataFrame:
    """One outcome per main sleep, including why a numeric estimate is unavailable."""
    output = []
    for session in sleep.loc[sleep.main.astype(bool)].itertuples():
        samples = (
            hr.loc[(hr.time_utc >= session.start_utc) & (hr.time_utc < session.end_utc)]
            .sort_values("time_utc")
            .copy()
        )
        result = {
            "date_local": session.date_local,
            "bpm": None,
            "physical_device_id": None,
            "computed_by": None,
        }
        if not session.eligible:
            reason = "main sleep session not eligible"
        elif samples.empty:
            reason = "no heart rate samples during main sleep"
        elif len(samples) < 6:
            reason = "fewer than six heart rate samples"
        else:
            reason = "no supported 30-minute window"
            best = resting_window(samples, session.end_utc)
            if best is not None:
                result.update(best)
        result["quality"] = (
            "derived from main sleep" if result["bpm"] is not None else f"missing: {reason}"
        )
        output.append(result)
    return pd.DataFrame(
        output, columns=["date_local", "bpm", "physical_device_id", "computed_by", "quality"]
    )


def resting_window(samples: pd.DataFrame, sleep_end) -> dict | None:
    """Lowest supported 30-minute mean; samples arrive in chronological order."""
    samples["support_end"] = (
        pd.concat([samples.time_utc.shift(-1), samples.time_utc + pd.Timedelta(minutes=5)], axis=1)
        .min(axis=1)
        .clip(upper=sleep_end)
    )
    # The final sample has no confirmed following support.
    samples.loc[samples.index[-1], "support_end"] = samples.time_utc.iloc[-1]
    best = None
    for start in samples.time_utc:
        end = start + pd.Timedelta(minutes=30)
        if end > sleep_end:
            break
        window = samples.loc[(samples.time_utc >= start) & (samples.time_utc < end)]
        if len(window) < 6:
            continue
        seconds = (window.support_end.clip(upper=end) - window.time_utc).dt.total_seconds()
        if seconds.sum() < 24 * 60:
            continue
        value = float((window.bpm * seconds).sum() / seconds.sum())
        if best is None or value < best["bpm"]:
            best = {
                "bpm": value,
                "physical_device_id": ", ".join(sorted(set(window.physical_device_id))),
                "computed_by": "app",
            }
    return best
