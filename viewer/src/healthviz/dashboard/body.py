"""Body detail: weight readings against the usual, and every reading of the period."""

import pandas as pd
import streamlit as st

from healthviz.analysis.sources import resolve_rows
from healthviz.analysis.usual import compare_point_readings
from healthviz.dashboard.charts import (
    daily_figure,
    filtered,
    local_times,
    overlap_audit,
    raw_data,
    show_number,
)
from healthviz.dashboard.context import day_picker, device_names, open_page
from healthviz.dashboard.format import day_text, kg


def readings_list(weights, names) -> pd.DataFrame:
    times = local_times(weights)
    return pd.DataFrame(
        {
            "Date": times.dt.date.map(day_text),
            "Time": times.dt.strftime("%H:%M"),
            "Weight": weights.kg.map(kg),
            "Source": weights.device_id.map(lambda d: names.get(d, d)),
        }
    ).iloc[::-1]


def render(context):
    daily, start, end = context.daily, context.start, context.end
    st.button("← Overview", on_click=open_page, args=("Overview",))
    weight = compare_point_readings(daily, "weight", start, end)
    show_number("Weight", weight, kg, kg, "readings")
    st.plotly_chart(
        daily_figure(daily, "weight", start, end, weight.usual, "kg"),
        width="stretch",
        key="body-weight",
    )
    day_picker(context, "body")
    tables = context.tables
    weights, _ = resolve_rows("weight", tables["weight"], tables["devices"], context.settings)
    weights = filtered(weights, start, end).sort_values("time_utc")
    st.subheader("Readings")
    if weights.empty:
        st.info("No weight readings in this period.")
    else:
        st.dataframe(readings_list(weights, device_names(context)), hide_index=True)
    raw_data(
        {"Weight readings": weights, "Weight source overlaps": overlap_audit(context, "weight")}
    )
