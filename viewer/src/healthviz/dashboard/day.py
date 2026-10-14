"""One day on its local clock: heart rate, movement per hour, the night before, workouts."""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.sources import resolve_rows
from healthviz.archive.values import parse_offset
from healthviz.dashboard.charts import filtered, hypnogram, local_times, raw_data
from healthviz.dashboard.context import derived, device_names
from healthviz.dashboard.format import bpm, count_text, day_text, kcal
from healthviz.dashboard.workouts import workout_list


def move(days):
    st.session_state["day"] = st.session_state["day"] + timedelta(days=days)


def back():
    st.session_state["view"] = None


def samples(context, metric, day):
    """Resolved rows of one local day; a three-day UTC window covers every offset."""
    raw = context.tables[metric]
    stamp = "time_utc" if "time_utc" in raw else "start_utc"
    lower = pd.Timestamp(day, tz="UTC") - pd.Timedelta(days=1)
    raw = raw.loc[(raw[stamp] >= lower) & (raw[stamp] < lower + pd.Timedelta(days=3))]
    resolved, _ = resolve_rows(metric, raw, context.tables["devices"], context.settings)
    return filtered(resolved, day, day)


def interval_start(frame):
    offsets = frame.utc_offset.map(
        {v: pd.Timedelta(minutes=parse_offset(v)) for v in frame.utc_offset.unique()}
    )
    return (frame.start_utc + offsets).dt.tz_localize(None)


def per_hour(frame, column, by=None):
    hours = interval_start(frame).dt.floor("h")
    keys = [hours] if by is None else [hours, frame[by]]
    return frame.groupby(keys)[column].sum(min_count=1)


def charts(context, day):
    heart = samples(context, "heart_rate", day)
    steps = samples(context, "steps", day)
    energy = samples(context, "calories", day)
    figures = []
    if not heart.empty:
        figure = go.Figure(
            go.Scatter(
                x=local_times(heart).dt.tz_localize(None),
                y=heart.bpm,
                mode="lines+markers",
                connectgaps=False,
            )
        )
        figures.append(("Heart rate", "bpm", figure))
    if not steps.empty:
        hourly = per_hour(steps, "count")
        figures.append(("Steps per hour", "steps", go.Figure(go.Bar(x=hourly.index, y=hourly))))
    if not energy.empty:
        figure = go.Figure()
        for kind, values in per_hour(energy, "kcal", "kind").groupby(level=1):
            figure.add_bar(
                x=values.index.get_level_values(0), y=values, name=f"{kind.title()} energy"
            )
        figures.append(("Energy per hour", "kcal", figure))
    for title, unit, figure in figures:
        figure.update_layout(
            title=title, xaxis_title="Local time", xaxis_tickformat="%H:%M", yaxis_title=unit
        )
        st.plotly_chart(figure, width="stretch", key="day-" + title)
    if not figures:
        st.info("No heart rate, steps or energy samples on this day.")
    return {"Heart rate samples": heart, "Step samples": steps, "Energy samples": energy}


def key_numbers(row):
    columns = st.columns(4)
    values = [
        ("Steps", row.steps, count_text),
        ("Active energy", row.active_kcal, kcal),
        ("Resting heart rate", row.resting_hr, bpm),
        ("Hours measured", row.worn_hours, lambda h: f"{h:.0f} h"),
    ]
    for column, (label, value, text) in zip(columns, values, strict=True):
        column.metric(label, "—" if pd.isna(value) else text(value))
    if not row.complete:
        st.caption("Incomplete day: too few hours with heart-rate samples; kept out of averages.")


def render(context):
    daily = context.daily
    first, last = daily.date_local.min(), daily.date_local.max()
    day = min(max(st.session_state.get("day") or context.end, first), last)
    st.session_state["day"] = day
    back_column, previous, following = st.columns([2, 1, 1])
    back_column.button("← Back", on_click=back)
    previous.button("◀ Previous day", on_click=move, args=(-1,), disabled=day <= first)
    following.button("Next day ▶", on_click=move, args=(1,), disabled=day >= last)
    st.subheader(day_text(day))
    row = daily.loc[daily.date_local == day]
    key_numbers(row.iloc[0])
    frames = charts(context, day)
    nights, workouts = derived(context)
    night = filtered(nights, day, day)
    if not night.empty and night.main.any():
        st.subheader("Night before")
        hypnogram(night.loc[night.main].iloc[0].to_dict(), context.tables["sleep_stages"])
    done = filtered(workouts, day, day)
    if not done.empty:
        st.subheader("Workouts")
        st.dataframe(workout_list(done, device_names(context)), hide_index=True)
    raw_data({"Selected day": row, **frames, "Day workouts": done})
