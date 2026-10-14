"""Period values against the user's usual: the same statistic over the 90 days before."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

USUAL_DAYS = 90
MIN_DAYS = 30
MIN_NIGHTS = 20
# Point readings: counted on any day, compared reading by reading.
READINGS = ("weight", "spo2")


@dataclass(frozen=True)
class Comparison:
    value: float | None
    usual: float | None
    spread: float | None
    counted: int
    total: int
    enough: bool
    latest: date | None = None

    @property
    def difference(self) -> float | None:
        if not self.enough or self.value is None or self.usual is None:
            return None
        return self.value - self.usual


def mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def spread(values: pd.Series) -> float | None:
    return float(values.std(ddof=0)) if len(values) else None


def windows(dates: pd.Series, start: date, end: date):
    """Masks for the period and for the usual window just before it."""
    return (dates >= start) & (dates <= end), (dates >= start - timedelta(days=USUAL_DAYS)) & (
        dates < start
    )


def compare(values: pd.Series, dates: pd.Series, start, end, minimum) -> Comparison:
    period, before = windows(dates, start, end)
    now, usual = values.loc[period].dropna(), values.loc[before].dropna()
    known = dates.loc[values.notna() & (dates <= end)]
    return Comparison(
        mean(now),
        mean(usual),
        spread(usual),
        len(now),
        (end - start).days + 1,
        len(usual) >= minimum,
        known.max() if len(known) else None,
    )


def compare_daily(daily: pd.DataFrame, metric: str, start: date, end: date) -> Comparison:
    """Daily totals and means count complete days only; sleep counts eligible nights."""
    counted = daily.sleep_eligible if metric == "sleep_min" else daily.complete
    values = pd.to_numeric(daily[metric]).where(counted.astype(bool))
    minimum = MIN_NIGHTS if metric == "sleep_min" else MIN_DAYS
    return compare(values, daily.date_local, start, end, minimum)


def compare_nights(
    nights: pd.DataFrame, column: str, start: date, end: date, *, clock=False
) -> Comparison:
    """Main eligible nights; clock times unwrap around 18:00 so 23:50 and 00:10 are 20 min apart."""
    if nights.empty or column not in nights:
        return compare(pd.Series(dtype=float), pd.Series(dtype=object), start, end, MIN_NIGHTS)
    chosen = nights.loc[nights.main.astype(bool) & nights.eligible.astype(bool)]
    values = pd.to_numeric(chosen[column])
    if clock:
        values = (values - 1080) % 1440 + 1080
    return compare(values, chosen.date_local, start, end, MIN_NIGHTS)


def compare_weekly_total(daily: pd.DataFrame, metric: str, start: date, end: date) -> Comparison:
    """Weekly totals: a day without any record counts as zero, an ambiguous day as unknown."""
    absent = daily[f"{metric}_quality"].eq("missing")
    values = pd.to_numeric(daily[metric]).mask(absent, 0.0)
    period, before = windows(daily.date_local, start, end)
    now, usual = values.loc[period].dropna(), values.loc[before].dropna()
    # Whole 7-day blocks counted back from the period start.
    blocks = daily.date_local.loc[usual.index].map(lambda d: ((start - d).days - 1) // 7)
    weeks = usual.groupby(blocks).agg(["sum", "size"])
    weeks = weeks.loc[weeks["size"] == 7, "sum"]
    return Comparison(
        mean(now) * 7 if len(now) else None,
        mean(usual) * 7 if len(usual) else None,
        spread(weeks) if len(weeks) > 1 else None,
        len(now),
        (end - start).days + 1,
        before.sum() >= MIN_DAYS,
    )


def compare_readings(readings: pd.DataFrame, start: date, end: date) -> Comparison:
    """Point readings (weight, SpO₂) count on any day: wearing the watch is irrelevant."""
    return compare(readings.value, readings.date_local, start, end, 1)


def compare_point_readings(daily: pd.DataFrame, metric: str, start: date, end: date) -> Comparison:
    """Weight or SpO₂ from the daily frame: one priority-resolved value per day with readings."""
    frame = daily[["date_local", metric]].dropna().rename(columns={metric: "value"})
    return compare_readings(frame, start, end)


def changes(comparisons: dict[str, tuple[str, Comparison, Callable[[float], str]]]) -> list[str]:
    """Up to three key numbers at least half a usual spread away, largest relative change first."""
    found = []
    for label, result, text in comparisons.values():
        difference = result.difference
        if difference is not None and result.spread and abs(difference) >= result.spread / 2:
            found.append((abs(difference) / result.spread, label, difference, text))
    found.sort(key=lambda item: -item[0])
    return [
        f"{label} {text(abs(d))} {'above' if d > 0 else 'below'} your usual"
        for _, label, d, text in found[:3]
    ] or ["No large changes from your usual"]
