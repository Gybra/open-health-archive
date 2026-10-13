from datetime import timedelta
from statistics import median

import pandas as pd

from healthviz.analysis.workouts import workout_days


def onset_sd(values: pd.Series) -> float:
    return float(((values - 18 * 60) % 1440).std())


def reduced_week(value, previous) -> bool:
    valid = [v for v in previous if pd.notna(v)]
    return bool(
        pd.notna(value) and len(valid) >= 4 and median(valid) > 0 and value < 0.7 * median(valid)
    )


def method_run(daily, metric, end):
    rows = daily.loc[(daily.date_local <= end) & daily[metric].notna()].sort_values("date_local")
    keys = [f"{metric}_physical_device_id", f"{metric}_computed_by"]
    if rows.empty or not set(keys).issubset(rows) or rows.iloc[-1][keys].isna().any():
        return daily.iloc[:0].copy()
    key = rows.iloc[-1][keys]
    changed = rows.loc[~rows[keys].eq(key).all(axis=1)]
    lower = (
        changed.date_local.iloc[-1] + timedelta(days=1)
        if not changed.empty
        else rows.date_local.iloc[0]
    )
    return daily.loc[(daily.date_local >= lower) & (daily.date_local <= end)].copy()


def compatible_history(daily, metric, as_of, window):
    rows = method_run(daily, metric, as_of)
    return rows.loc[
        (rows.date_local >= as_of - timedelta(days=window))
        & (rows.date_local < as_of)
        & rows.complete
        & rows[metric].notna()
    ]


def observations(
    daily: pd.DataFrame, sleep: pd.DataFrame, workouts: pd.DataFrame, as_of
) -> list[str]:
    if daily.empty:
        return []
    messages = []
    today = daily.loc[daily.date_local == as_of]
    if not today.empty and today.iloc[0].complete and pd.notna(today.iloc[0].resting_hr):
        prior = compatible_history(daily, "resting_hr", as_of, 30)
        if len(prior) >= 15:
            mean, sd = prior.resting_hr.mean(), prior.resting_hr.std()
            value = today.iloc[0].resting_hr
            if mean > 0 and value > mean + 2 * sd:
                messages.append(
                    f"Resting HR {value:.1f} bpm is above the preceding 30-day mean "
                    f"{mean:.1f} bpm + 2 SD ({sd:.1f}); {len(prior)} complete days, "
                    "same source and method. Descriptive comparison only."
                )
    if not sleep.empty:
        nights = sleep.loc[sleep.main & sleep.eligible & (sleep.date_local <= as_of)]
        recent = nights.loc[
            (nights.date_local > as_of - timedelta(days=28))
            & nights.date_local.isin(method_run(daily, "sleep_min", as_of).date_local)
        ]
        if len(recent) >= 7:
            messages.append(
                f"Sleep onset SD is {onset_sd(recent.onset_wall_min):.1f} minutes "
                f"over {len(recent)} eligible nights in the last 28 days "
                "(clock times unwrapped around 18:00)."
            )
        week = as_of - timedelta(days=as_of.weekday() + 7)
        nights = nights.loc[
            nights.date_local.isin(
                method_run(daily, "sleep_min", week + timedelta(days=6)).date_local
            )
        ]
        latest = nights.loc[
            (nights.date_local >= week) & (nights.date_local < week + timedelta(days=7))
        ]
        prior = nights.loc[
            (nights.date_local >= week - timedelta(days=28)) & (nights.date_local < week)
        ]
        if latest.date_local.nunique() == 7 and len(prior) >= 14:
            difference = latest.sleep_min.sum() - 7 * prior.sleep_min.mean()
            messages.append(
                f"Week {week.isoformat()}: measured sleep differs by {difference:+.0f} "
                f"minutes from 7 × the prior 28-day personal mean "
                f"({prior.sleep_min.mean():.0f} min/night, {len(prior)} eligible nights). "
                "This is not a physiological debt estimate."
            )
    messages.extend(weekly_observations(daily, as_of))
    if not workouts.empty:
        eligible_days = set(daily.loc[daily.complete, "date_local"])
        eligible = workouts.loc[
            (workouts.date_local <= as_of)
            & workouts.apply(
                lambda row: all(day in eligible_days and day <= as_of for day in workout_days(row)),
                axis=1,
            )
            & workouts.quality.ne("ambiguous")
        ].copy()
        duration = eligible.duration_s.fillna(
            (eligible.end_utc - eligible.start_utc).dt.total_seconds()
        )
        eligible["pace"] = duration / eligible.distance_m.where(eligible.distance_m > 0) * 1000 / 60
        for kind, group in eligible.groupby("type"):
            distances = group.loc[group.distance_m > 0]
            if not distances.empty:
                best = distances.sort_values("distance_m").iloc[-1]
                messages.append(
                    f"{kind}: longest recorded distance {best.distance_m / 1000:.2f} km "
                    f"on {best.date_local}; {len(distances)} eligible workouts."
                )
                if kind in ("walking", "running", "hiking"):
                    pace = distances.loc[distances.pace > 0].sort_values("pace")
                    if not pace.empty:
                        best = pace.iloc[0]
                        messages.append(
                            f"{kind}: best recorded average pace {best.pace:.2f} min/km "
                            f"on {best.date_local}; recorded duration/distance, eligible days only."
                        )
    return messages


def weekly_observations(daily, as_of):
    week = as_of - timedelta(days=as_of.weekday() + 7)
    messages = []
    for metric, label in [("steps", "steps"), ("workout_min", "recorded workout minutes")]:
        frame = method_run(daily, metric, week + timedelta(days=6))
        frame["week"] = frame.date_local.map(lambda d: d - timedelta(days=d.weekday()))
        weekly = {}
        for start, group in frame.groupby("week"):
            if len(group) == 7 and group.complete.all() and group[metric].notna().all():
                weekly[start] = float(group[metric].sum())
        if week not in weekly:
            continue
        history = [v for start, v in weekly.items() if week - timedelta(weeks=8) <= start < week]
        if reduced_week(weekly[week], history):
            messages.append(
                f"Week {week.isoformat()}: {label} {weekly[week]:.0f}, below 70% "
                f"of the preceding 8-week median {median(history):.0f}; "
                f"{len(history)} complete weeks."
            )
    return messages
