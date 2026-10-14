"""Activity detail: daily movement, workouts one by one, and where the routes went."""

import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.observations import activity_observations
from healthviz.analysis.usual import compare_daily, compare_weekly_total
from healthviz.dashboard import maps, workouts
from healthviz.dashboard.charts import (
    daily_figure,
    filtered,
    notes,
    overlap_audit,
    raw_data,
    show_number,
)
from healthviz.dashboard.context import derived, open_page, remember, restore
from healthviz.dashboard.format import count_text, kcal, km, minutes_text

# Daily metric → (label, chart tab, unit, scale, value text).
DAILY = {
    "steps": ("Steps per day", "Steps", "steps", 1, count_text),
    "distance": ("Distance per day", "Distance", "km", 1 / 1000, km),
    "active_kcal": ("Active energy per day", "Active energy", "kcal", 1, kcal),
    "total_kcal": ("Total energy per day", "Total energy", "kcal", 1, kcal),
}


def daily_view(context, results):
    daily, start, end = context.daily, context.start, context.end
    tabs = st.tabs([tab for _, tab, _, _, _ in DAILY.values()])
    for tab, (metric, (_, _, unit, scale, _)) in zip(tabs, DAILY.items(), strict=True):
        with tab:
            figure = daily_figure(
                daily, metric, start, end, results[metric].usual, unit, bars=True, scale=scale
            )
            st.plotly_chart(figure, width="stretch", key="activity-" + metric)
    st.caption(
        "Active and total energy are different measures, never added. Workouts are not "
        "added to daily energy; no calorie balance is computed."
    )
    notes(activity_observations(daily, derived(context)[1], end))
    raw_data(
        {
            "Activity weekly totals": period_summary(filtered(daily, start, end), "week"),
            "Steps source overlaps": overlap_audit(context, "steps"),
            "Distance source overlaps": overlap_audit(context, "distance"),
            "Calories source overlaps": overlap_audit(context, "calories"),
        }
    )


def render(context):
    daily, start, end = context.daily, context.start, context.end
    st.button("← Overview", on_click=open_page, args=("Overview",))
    results = {metric: compare_daily(daily, metric, start, end) for metric in DAILY}
    columns = st.columns(len(DAILY) + 1)
    for column, (metric, (label, _, _, _, text)) in zip(columns, DAILY.items(), strict=False):
        with column:
            show_number(label, results[metric], text, text, "days")
    with columns[-1]:
        weekly = compare_weekly_total(daily, "workout_min", start, end)
        show_number("Workout time per week", weekly, minutes_text, minutes_text)
    views = ["Daily", "Workouts", "Routes"]
    restore("activity_view", views)
    # Highlight "Daily" until another view is picked.
    st.session_state.setdefault("activity_view", "Daily")
    view = st.segmented_control("Show", views, key="activity_view")
    remember("activity_view", view)
    if view == "Workouts":
        workouts.render(context)
    elif view == "Routes":
        maps.render(context)
    else:
        daily_view(context, results)
