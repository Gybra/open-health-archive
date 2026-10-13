import calendar
from datetime import timedelta

import pandas as pd

from healthviz.analysis.heart import resting_from_sleep
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import annotate, resolve_rows, source_rank
from healthviz.analysis.workouts import split_workout_days
from healthviz.archive.values import parse_offset
from healthviz.settings import Settings

METRICS = [
    "steps",
    "distance",
    "active_kcal",
    "total_kcal",
    "hr_mean",
    "hr_min",
    "hr_max",
    "resting_hr",
    "weight",
    "spo2",
    "sleep_min",
    "workout_min",
]
FALLBACK = {
    "steps": ("steps", "count"),
    "distance": ("distance", "m"),
    "active_kcal": ("active_kcal", "kcal"),
    "sleep_duration": ("sleep_min", "min"),
}


def selected_tables(tables, devices, settings):
    return {
        name: resolve_rows(name, frame, devices, settings)[0]
        if name not in ("devices", "sleep_stages", "daily_vendor_summaries")
        else frame.copy()
        for name, frame in tables.items()
    }


def daily_summary(
    tables: dict[str, pd.DataFrame], devices: pd.DataFrame, settings: Settings
) -> pd.DataFrame:
    selected = selected_tables(tables, devices, settings)
    nights = sleep_summary(selected["sleep_sessions"], tables["sleep_stages"])
    workout_parts = split_workout_days(selected["workouts"])
    dates = set()
    for frame in [*selected.values(), nights, workout_parts]:
        if "date_local" in frame:
            dates.update(frame.date_local.dropna())
    if not dates:
        return pd.DataFrame(
            columns=["date_local", "worn_hours", "complete", "sleep_eligible", *METRICS]
        )
    days = {
        day.date(): {
            "date_local": day.date(),
            "worn_hours": 0,
            "complete": False,
            "sleep_eligible": False,
        }
        for day in pd.date_range(min(dates), max(dates))
    }
    for row in days.values():
        for metric in METRICS:
            row.update(
                {
                    metric: None,
                    f"{metric}_physical_device_id": None,
                    f"{metric}_computed_by": None,
                    f"{metric}_quality": "missing",
                    f"{metric}_fallback": False,
                }
            )
    hr = selected["heart_rate"]
    for day, group in hr.groupby("date_local"):
        row = days[day]
        row["worn_hours"] = group.hour_start_utc.nunique()
        row["complete"] = row["worn_hours"] >= settings.worn_hours_threshold
        for key, operation in [("hr_mean", "mean"), ("hr_min", "min"), ("hr_max", "max")]:
            set_metric(row, key, getattr(group.bpm, operation)(), group)
    for table, col, metric in [
        ("steps", "count", "steps"),
        ("distance", "distance_m", "distance"),
        ("weight", "kg", "weight"),
        ("spo2", "percent", "spo2"),
        ("resting_heart_rate", "bpm", "resting_hr"),
    ]:
        for day, group in selected[table].groupby("date_local"):
            ambiguous = (group.quality == "ambiguous").any()
            value = (
                None
                if ambiguous
                else group[col].mean()
                if table in ("spo2", "resting_heart_rate", "weight")
                else group[col].sum(min_count=1)
            )
            set_metric(days[day], metric, value, group)
    for (day, kind), group in selected["calories"].groupby(["date_local", "kind"]):
        value = None if (group.quality == "ambiguous").any() else group.kcal.sum(min_count=1)
        set_metric(days[day], f"{kind}_kcal", value, group)
    for session in nights.loc[nights.main].to_dict("records"):
        day = session["date_local"]
        set_metric(days[day], "sleep_min", session["sleep_min"], pd.DataFrame([session]))
        days[day]["sleep_eligible"] = bool(session["eligible"])
    for day, group in workout_parts.groupby("date_local"):
        set_metric(
            days[day],
            "workout_min",
            None if (group.quality == "ambiguous").any() else group.minutes.sum(min_count=1),
            group,
        )
    apply_fallback(days, tables, devices, settings)
    eligible_nights = (
        nights.loc[nights.date_local.map(lambda day: days[day]["complete"])]
        if not nights.empty
        else nights
    )
    for resting in resting_from_sleep(hr, eligible_nights).to_dict("records"):
        row = days[resting["date_local"]]
        if pd.isna(row["resting_hr"]):
            row.update(
                {
                    "resting_hr": resting["bpm"],
                    "resting_hr_physical_device_id": resting["physical_device_id"],
                    "resting_hr_computed_by": "app",
                    "resting_hr_quality": "derived from main sleep",
                }
            )
    return pd.DataFrame(days.values()).sort_values("date_local").reset_index(drop=True)


def set_metric(row, metric, value, source):
    row[metric] = value
    row[f"{metric}_physical_device_id"] = ", ".join(sorted(set(source.physical_device_id.dropna())))
    methods = source["computed_by"] if "computed_by" in source else pd.Series(["device"])
    row[f"{metric}_computed_by"] = ", ".join(sorted(set(methods.dropna())))
    row[f"{metric}_quality"] = (
        "ambiguous"
        if (source.quality == "ambiguous").any()
        else "estimated allocation"
        if source.allocation_estimated.any()
        else "observed"
    )


def raw_days(frame, metric, settings):
    if frame.empty:
        return set()
    rows = annotate(frame, metric, settings)
    days = set(rows.date_local)
    if metric in ("steps", "distance", "calories"):
        for row in rows.itertuples():
            offset = pd.Timedelta(minutes=parse_offset(row.utc_offset))
            start, end = (
                (row.start_utc + offset).date(),
                (row.end_utc + offset - pd.Timedelta(microseconds=1)).date(),
            )
            days.update(d.date() for d in pd.date_range(start, end))
    return days


def apply_fallback(days, tables, devices, settings):
    summaries = tables["daily_vendor_summaries"]
    for vendor_metric, (metric, unit) in FALLBACK.items():
        table = (
            "calories"
            if metric == "active_kcal"
            else "sleep_sessions"
            if metric == "sleep_min"
            else metric
        )
        raw = tables[table]
        if table == "calories":
            raw = raw.loc[raw.kind == "active"]
        blocked = raw_days(raw, table, settings)
        candidates = summaries.loc[summaries.metric == vendor_metric]
        for day, group in candidates.groupby("date_local"):
            if day in blocked or day not in days:
                continue
            records = group.to_dict("records")
            choice = min(
                records,
                key=lambda r: source_rank(
                    vendor_metric,
                    tuple(
                        "" if pd.isna(r[c]) else r[c] for c in ("device_id", "ingest", "source_app")
                    ),
                    devices,
                    settings,
                ),
            )
            if choice["unit"] != unit:
                days[day][f"{metric}_quality"] = "invalid fallback unit"
                continue
            days[day].update(
                {
                    metric: choice["value"],
                    f"{metric}_physical_device_id": settings.device_aliases.get(
                        choice["device_id"], choice["device_id"]
                    ),
                    f"{metric}_computed_by": "vendor",
                    f"{metric}_quality": "vendor fallback",
                    f"{metric}_fallback": True,
                }
            )


def period_summary(daily: pd.DataFrame, period: str) -> pd.DataFrame:
    if period not in ("week", "month"):
        raise ValueError("unknown period")
    if daily.empty:
        return pd.DataFrame(columns=["period", "covered_days", "expected_days", "complete"])
    frame = daily.copy()
    frame["period"] = frame.date_local.map(
        lambda d: d - timedelta(days=d.weekday()) if period == "week" else d.replace(day=1)
    )
    result = []
    for start, group in frame.groupby("period"):
        expected = 7 if period == "week" else calendar.monthrange(start.year, start.month)[1]
        covered = int(group.complete.sum())
        row = {
            "period": start,
            "covered_days": covered,
            "expected_days": expected,
            "complete": covered == expected,
            "nights": int(group.sleep_eligible.sum()),
        }
        for metric in METRICS:
            eligible = group.sleep_eligible if metric == "sleep_min" else group.complete
            count = int((eligible & group[metric].notna()).sum())
            row[f"{metric}_covered_days"] = count
            row[f"{metric}_complete"] = count == expected
            row[metric] = (
                group[metric].sum(min_count=1)
                if metric in ("steps", "distance", "active_kcal", "total_kcal", "workout_min")
                else group.loc[
                    group.sleep_eligible if metric == "sleep_min" else group.complete, metric
                ].mean()
            )
        result.append(row)
    return pd.DataFrame(result)
