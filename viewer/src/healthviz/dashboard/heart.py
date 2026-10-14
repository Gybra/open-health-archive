"""Heart detail: resting and daily heart rate, blood oxygen and how many hours were measured."""

import streamlit as st

from healthviz.analysis.observations import heart_observations
from healthviz.analysis.usual import compare_daily, compare_point_readings
from healthviz.dashboard.charts import (
    coverage_figure,
    daily_figure,
    filtered,
    notes,
    overlap_audit,
    range_figure,
    raw_data,
    show_number,
)
from healthviz.dashboard.context import open_page
from healthviz.dashboard.format import bpm, percent

COLUMNS = ["date_local", "worn_hours", "complete", "hr_mean", "hr_min", "hr_max"]


def render(context):
    daily, start, end = context.daily, context.start, context.end
    st.button("← Overview", on_click=open_page, args=("Overview",))
    resting = compare_daily(daily, "resting_hr", start, end)
    oxygen = compare_point_readings(daily, "spo2", start, end)
    period = filtered(daily, start, end)
    columns = st.columns(4)
    with columns[0]:
        show_number("Resting heart rate", resting, bpm, bpm, "days")
    with columns[1]:
        show_number("Average heart rate", compare_daily(daily, "hr_mean", start, end), bpm, bpm)
    with columns[2]:
        show_number("Blood oxygen", oxygen, percent, percent, "readings")
    with columns[3]:
        hours = period.worn_hours.mean() if not period.empty else None
        st.metric("Hours measured per day", "—" if hours is None else f"{hours:.1f} h")
        st.caption(f"complete day: {context.settings.worn_hours_threshold} h or more")
    left, right = st.columns(2)
    with left:
        st.subheader("Resting heart rate")
        st.plotly_chart(
            daily_figure(daily, "resting_hr", start, end, resting.usual, "bpm"),
            width="stretch",
            key="heart-resting",
        )
        st.subheader("Blood oxygen")
        st.plotly_chart(
            daily_figure(daily, "spo2", start, end, oxygen.usual, "%"),
            width="stretch",
            key="heart-spo2",
        )
    with right:
        st.subheader("Lowest, average and highest per day")
        st.plotly_chart(range_figure(daily, start, end), width="stretch", key="heart-range")
        st.subheader("Hours measured")
        st.plotly_chart(
            coverage_figure(daily, start, end, context.settings.worn_hours_threshold),
            width="stretch",
            key="heart-coverage",
        )
        st.caption("Hours with heart-rate samples: a coverage proxy, not proven wear time.")
    notes(heart_observations(daily, end))
    resting_columns = [c for c in period.columns if c.startswith(("resting_hr", "spo2"))]
    raw_data(
        {
            "Daily heart values": period[COLUMNS + resting_columns],
            "Heart rate source overlaps": overlap_audit(context, "heart_rate"),
            "Resting heart rate source overlaps": overlap_audit(context, "resting_heart_rate"),
            "Blood oxygen source overlaps": overlap_audit(context, "spo2"),
        }
    )
