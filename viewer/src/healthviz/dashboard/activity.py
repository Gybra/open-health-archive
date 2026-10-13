import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import filtered, show_trend, summary_table


def render(tables, daily, settings, *, start, end):
    frame = filtered(daily, start, end)
    for metric, title, unit in [
        ("steps", "Daily steps", "count"),
        ("distance", "Daily distance", "m"),
        ("active_kcal", "Active calories", "kcal"),
        ("total_kcal", "Total calories", "kcal"),
    ]:
        show_trend(frame, metric, title, unit)
    st.caption(
        "Active and total calories are different measures, never added. Workouts are "
        "not added to daily calories; no calorie balance is computed."
    )
    summary_table(period_summary(frame, "week"), "Activity weekly totals")
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    workouts = filtered(workouts, start, end)
    duration = workouts.duration_s.fillna(
        (workouts.end_utc - workouts.start_utc).dt.total_seconds()
    )
    workouts["kcal_per_min"] = workouts.active_kcal / (duration.where(duration > 0) / 60)
    summary_table(workouts, "Workout calories")
    summary_table(
        workouts.groupby("type")[["active_kcal", "total_kcal", "kcal_per_min"]]
        .mean()
        .reset_index(),
        "Workout calories by type",
    )
