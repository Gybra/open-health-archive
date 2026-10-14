import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import filtered, hypnogram, local_times, summary_table


def render(context):
    tables, daily, settings, start, end = (
        context.tables,
        context.daily,
        context.settings,
        context.start,
        context.end,
    )
    choices = filtered(daily, start, end).date_local.tolist()
    if not choices:
        st.info("No dates in this range.")
        return
    wanted = st.session_state.get("day")
    index = choices.index(wanted) if wanted in choices else len(choices) - 1
    day = st.selectbox("Day", choices, index=index)
    row = daily.loc[daily.date_local == day]
    summary_table(row, "Selected day")
    st.caption(
        f"HR sample-hour coverage: {int(row.iloc[0].worn_hours)} · complete: "
        f"{bool(row.iloc[0].complete)}. This is a coverage proxy, not proven wear "
        f"time."
    )
    for metric, col, label in [
        ("heart_rate", "bpm", "Heart rate"),
        ("steps", "count", "Steps"),
        ("calories", "kcal", "Calories"),
    ]:
        raw = tables[metric]
        timestamp = "time_utc" if "time_utc" in raw else "start_utc"
        lower = pd.Timestamp(day, tz="UTC") - pd.Timedelta(days=1)
        upper = lower + pd.Timedelta(days=3)
        raw = raw.loc[(raw[timestamp] >= lower) & (raw[timestamp] < upper)]
        resolved, _ = resolve_rows(metric, raw, tables["devices"], settings)
        resolved = filtered(resolved, day, day)
        if resolved.empty:
            st.info(f"{label}: no samples.")
            continue
        x = (
            local_times(resolved).dt.tz_localize(None)
            if metric == "heart_rate"
            else resolved.start_utc
        )
        fig = go.Figure()
        groups = resolved.groupby("kind") if metric == "calories" else [(label, resolved)]
        for name, group in groups:
            fig.add_trace(
                go.Scatter(
                    x=x.loc[group.index],
                    y=group[col],
                    name=name,
                    mode="lines+markers",
                    connectgaps=False,
                )
            )
        fig.update_layout(
            title=label,
            xaxis_title="Recorded local time" if metric == "heart_rate" else "UTC time",
            yaxis_title=col,
            xaxis_tickformat="%Y-%m-%d %H:%M",
        )
        st.plotly_chart(fig, width="stretch")
    sessions, _ = resolve_rows(
        "sleep_sessions", tables["sleep_sessions"], tables["devices"], settings
    )
    nights = filtered(sleep_summary(sessions, tables["sleep_stages"]), day, day)
    if not nights.empty:
        hypnogram(nights.loc[nights.main].iloc[0].to_dict(), tables["sleep_stages"])
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    summary_table(filtered(workouts, day, day), "Day workouts")
