import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard import maps, workouts
from healthviz.dashboard.charts import filtered, show_trend, summary_table


def daily_view(context):
    tables, daily, settings, start, end = (
        context.tables,
        context.daily,
        context.settings,
        context.start,
        context.end,
    )
    frame = filtered(daily, start, end)
    for metric, title, unit in [
        ("steps", "Daily steps", "count"),
        ("distance", "Daily distance", "m"),
        ("active_kcal", "Active calories", "kcal"),
        ("total_kcal", "Total calories", "kcal"),
    ]:
        show_trend(daily, metric, title, unit, start=start, end=end)
    st.caption(
        "Active and total calories are different measures, never added. Workouts are "
        "not added to daily calories; no calorie balance is computed."
    )
    summary_table(period_summary(frame, "week"), "Activity weekly totals")
    done, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    done = filtered(done, start, end)
    duration = done.duration_s.fillna((done.end_utc - done.start_utc).dt.total_seconds())
    done["kcal_per_min"] = done.active_kcal / (duration.where(duration > 0) / 60)
    summary_table(done, "Workout calories")
    summary_table(
        done.groupby("type")[["active_kcal", "total_kcal", "kcal_per_min"]].mean().reset_index(),
        "Workout calories by type",
    )


VIEWS = {"Daily": daily_view, "Workouts": workouts.render, "Routes": maps.render}


def render(context):
    view = st.segmented_control("Show", list(VIEWS), key="activity_view") or "Daily"
    VIEWS[view](context)
