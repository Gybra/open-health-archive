"""Readable values: ISO dates with weekday, 24-hour clock, metric units."""

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from healthviz.analysis.usual import Comparison

THIN = "\u202f"  # narrow no-break space between thousands


def day_text(day: date) -> str:
    return f"{day:%a %Y-%m-%d}"


def minutes_text(minutes: float) -> str:
    hours, rest = divmod(round(minutes), 60)
    return f"{hours} h {rest:02d}" if hours else f"{rest} min"


def count_text(value: float) -> str:
    return f"{round(value):,}".replace(",", THIN)


def pace_text(min_per_km: float) -> str:
    minutes, seconds = divmod(round(min_per_km * 60), 60)
    return f"{minutes}:{seconds:02d} /km"


def clock_text(minutes_after_midnight: float) -> str:
    hours, minutes = divmod(round(minutes_after_midnight) % 1440, 60)
    return f"{hours:02d}:{minutes:02d}"


def difference_text(result: Comparison, text) -> str:
    """Neutral direction, never a judgement: ▲/▼ only say higher or lower."""
    if result.value is None:
        return ""
    difference = result.difference
    if difference is None:
        return "not enough history yet"
    shown = text(abs(difference))
    if abs(difference) < 0.1 * (result.spread or 0) or shown == text(0):
        return "≈ usual"
    return f"{'▲' if difference > 0 else '▼'} {shown} vs usual"


def measured_text(result: Comparison, noun: str) -> str:
    if noun != "readings":
        if not result.counted and result.latest:
            return f"no data in this period · last {day_text(result.latest)}"
        return f"{result.counted} of {result.total} {noun} measured"
    latest = f" · latest {day_text(result.latest)}" if result.latest else ""
    if not result.counted:
        return f"no readings in this period{latest}"
    return f"{result.counted} days with readings{latest}"


def stamp_text(iso_utc: str | None, timezone: str) -> str:
    """A UTC timestamp from a status file, shown on the local clock."""
    try:
        return f"{pd.Timestamp(iso_utc).tz_convert(ZoneInfo(timezone)):%Y-%m-%d %H:%M}"
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return str(iso_utc)


def bpm(value):
    return f"{value:.0f} bpm"


def kcal(value):
    return f"{count_text(value)} kcal"


def km(metres):
    return f"{metres / 1000:.1f} km"


def kg(value):
    return f"{value:.1f} kg"


def percent(value):
    return f"{value:.1f} %"
