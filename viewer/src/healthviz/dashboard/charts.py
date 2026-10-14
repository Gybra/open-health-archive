import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.sources import resolve_rows
from healthviz.analysis.usual import READINGS
from healthviz.archive.values import parse_offset
from healthviz.dashboard.format import difference_text, measured_text

FADED, AVERAGE, USUAL = "#93b4ef", "#1f6feb", "#9ca3af"
# Levels (heart rate, weight, SpO₂) are read against their own range; amounts start at zero.
LEVELS = ("resting_hr", "hr_mean", "hr_min", "hr_max", "weight", "spo2")
STAGE_COLORS = {"deep": "#1e40af", "light": "#93c5fd", "rem": "#a855f7", "awake": "#fca5a5"}
STAGE_NAMES = {"deep": "Deep", "light": "Light", "rem": "REM", "awake": "Awake"}


def filtered(frame, start, end):
    return (
        frame.loc[(frame.date_local >= start) & (frame.date_local <= end)].copy()
        if "date_local" in frame
        else frame.iloc[:0].copy()
    )


def trend(
    frame: pd.DataFrame, metric: str, title: str, unit: str, *, start=None, end=None
) -> go.Figure:
    figure = go.Figure()
    if frame.empty:
        figure.update_layout(title=title, yaxis_title=unit)
        return figure
    frame = frame.sort_values("date_local")
    visible = pd.Series(True, index=frame.index)
    if start is not None:
        visible &= frame.date_local >= start
    if end is not None:
        visible &= frame.date_local <= end
    eligible = frame.sleep_eligible if metric == "sleep_min" else frame.complete
    value = pd.to_numeric(frame[metric]).where(eligible)
    dates = frame.loc[visible, "date_local"]
    figure.add_trace(
        go.Scatter(
            x=dates, y=value.loc[visible], name="Daily", mode="lines+markers", connectgaps=False
        )
    )
    partial = frame.loc[visible & ~eligible & frame[metric].notna()]
    figure.add_trace(
        go.Scatter(
            x=partial.date_local,
            y=partial[metric],
            name="Incomplete · excluded",
            mode="markers",
            marker={"color": "#888", "symbol": "x"},
        )
    )
    indexed = pd.Series(value.to_numpy(), index=pd.to_datetime(frame.date_local))
    for window, minimum in [(7, 4), (30, 15)]:
        # The viewport must not change a historical calendar-window statistic.
        mean = indexed.rolling(f"{window}D", min_periods=minimum).mean().where(eligible.to_numpy())
        figure.add_trace(
            go.Scatter(
                x=dates,
                y=mean.iloc[visible.to_numpy()],
                name=f"{window}-day mean",
                connectgaps=False,
            )
        )
    source_cols = [f"{metric}_physical_device_id", f"{metric}_computed_by"]
    if set(source_cols).issubset(frame.columns):
        previous = None
        for row in frame.loc[frame[metric].notna()].to_dict("records"):
            key = tuple(row[c] for c in source_cols)
            in_range = (start is None or row["date_local"] >= start) and (
                end is None or row["date_local"] <= end
            )
            if previous is not None and key != previous and in_range:
                figure.add_vline(
                    x=row["date_local"].isoformat(), line_dash="dash", line_color="#777"
                )
            previous = key
    figure.update_layout(
        title=title,
        xaxis_title="Local date",
        xaxis_tickformat="%Y-%m-%d",
        yaxis_title=unit,
        legend={"orientation": "h"},
        height=340,
    )
    return figure


def counted(daily, metric):
    """Days that enter averages: eligible nights, complete days, or any day for readings."""
    if metric == "sleep_min":
        return daily.sleep_eligible.astype(bool)
    if metric in READINGS:
        return daily[metric].notna()
    return daily.complete.astype(bool)


def compact(figure, unit, height=260):
    figure.update_layout(
        yaxis_title=unit,
        xaxis_tickformat="%Y-%m-%d",
        legend={"orientation": "h", "y": 1.12},
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        height=height,
    )
    return figure


def daily_figure(daily, metric, start, end, usual, unit, *, bars=False, scale=1.0) -> go.Figure:
    """Single days faded, the 7-day average bold, the user's usual dashed."""
    figure = go.Figure()
    if daily.empty:
        return compact(figure, unit)
    daily = daily.sort_values("date_local")
    values = pd.to_numeric(daily[metric]).where(counted(daily, metric)) * scale
    visible = ((daily.date_local >= start) & (daily.date_local <= end)).to_numpy()
    dates = daily.date_local[visible]
    single = (go.Bar if bars else go.Scatter)(x=dates, y=values[visible], name="single days")
    if bars:
        single.update(marker_color=FADED)
    else:
        single.update(mode="markers", marker={"color": FADED, "size": 6})
    figure.add_trace(single)
    if metric not in READINGS:
        # Calendar window over the whole history, so the viewport never changes the average.
        indexed = pd.Series(values.to_numpy(), index=pd.to_datetime(daily.date_local))
        mean = indexed.rolling("7D", min_periods=4).mean().where(values.notna().to_numpy())
        figure.add_scatter(
            x=dates,
            y=mean.to_numpy()[visible],
            name="7-day average",
            line={"color": AVERAGE, "width": 2.4},
            connectgaps=False,
        )
    if usual is not None:
        figure.add_scatter(
            x=[start, end],
            y=[usual * scale] * 2,
            name="your usual",
            mode="lines",
            line={"color": USUAL, "dash": "dash"},
        )
    if metric not in LEVELS:
        figure.update_yaxes(rangemode="tozero")
    return compact(figure, unit)


def stages_figure(nights, usual_min) -> go.Figure:
    """Stacked recorded stage time per main night, in hours; missing stages stay gaps."""
    figure = go.Figure()
    for stage, color in STAGE_COLORS.items():
        column = nights.get(f"{stage}_min", pd.Series(index=nights.index, dtype=float))
        figure.add_bar(
            x=nights.date_local, y=column / 60, name=STAGE_NAMES[stage], marker_color=color
        )
    if usual_min is not None and not nights.empty:
        figure.add_scatter(
            x=[nights.date_local.min(), nights.date_local.max()],
            y=[usual_min / 60] * 2,
            name="your usual",
            mode="lines",
            line={"color": USUAL, "dash": "dash"},
        )
    figure.update_layout(barmode="stack")
    return compact(figure, "hours asleep", height=300)


def clock_figure(nights) -> go.Figure:
    """One bar per night from falling asleep to waking, on an axis from 18:00 to 18:00."""
    onset = (nights.onset_wall_min - 1080) % 1440
    wake = (nights.wake_wall_min - 1080) % 1440
    length = (wake - onset) % 1440
    figure = go.Figure(go.Bar(x=nights.date_local, base=onset, y=length, marker_color=AVERAGE))
    ticks = list(range(0, 1441, 120))
    axis = {"tickvals": ticks, "ticktext": [f"{(18 + t // 60) % 24:02d}:00" for t in ticks]}
    if not nights.empty:
        # Reversed: evening at the top, morning at the bottom, half an hour of margin.
        axis["range"] = [int((onset + length).max()) + 30, int(onset.min()) - 30]
    figure.update_layout(showlegend=False, yaxis=axis)
    return compact(figure, "local time", height=300)


def raw_data(frames: dict[str, pd.DataFrame]) -> None:
    """The only place for UTC times, offsets and archive column names."""
    with st.expander("Raw data and sources"):
        for title, frame in frames.items():
            summary_table(frame, title)


def overlap_audit(context, metric) -> pd.DataFrame:
    """Rows of days where several sources report the metric, or one source overlaps itself."""
    tables = context.tables
    _, audit = resolve_rows(metric, tables[metric], tables["devices"], context.settings)
    audit = filtered(audit, context.start, context.end)
    if audit.empty:
        return audit
    sources = (
        audit[["date_local", "device_id", "ingest", "source_app"]]
        .drop_duplicates()
        .groupby("date_local")
        .size()
    )
    return audit.loc[
        audit.date_local.isin(sources.loc[sources > 1].index) | audit.quality.eq("ambiguous")
    ]


def show_number(label, result, value_text, change_text, noun=None):
    """A key number with its neutral difference from the usual and, optionally, its coverage."""
    st.metric(
        label,
        "—" if result.value is None else value_text(result.value),
        delta=difference_text(result, change_text) or None,
        delta_color="off",
        delta_arrow="off",
    )
    if noun:
        st.caption(measured_text(result, noun))


def notes(messages: list[str]) -> None:
    """Archive text such as workout types is shown as plain text, never as markdown."""
    st.subheader("Notes")
    if not messages:
        st.caption("Nothing to note against your own history, or not enough history yet.")
    for message in messages:
        st.text(message, width="stretch")


def summary_table(frame: pd.DataFrame, title: str) -> None:
    st.subheader(title)
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={"complete": st.column_config.CheckboxColumn("HR coverage complete")},
    )
    # Escaping spreadsheet formulas changes exported text only, not archived values.
    export = frame.copy()
    for col in export.select_dtypes(include=["string", "object"]):
        export[col] = export[col].map(
            lambda v: (
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
            )
        )
    st.download_button(
        "Download CSV",
        export.to_csv(index=False).encode(),
        file_name=title.lower().replace(" ", "-") + ".csv",
        mime="text/csv",
        key="csv-" + title,
    )


def show_trend(frame, metric, title, unit, *, start=None, end=None):
    st.plotly_chart(
        trend(frame, metric, title, unit, start=start, end=end),
        width="stretch",
        key="trend-" + metric,
    )


def select_record(frame, label):
    records = {(row["ingest"], row["record_id"]): row for row in frame.to_dict("records")}

    def readable(key):
        row = records[key]
        local = row["start_utc"] + pd.Timedelta(minutes=parse_offset(row["utc_offset"]))
        return f"{local:%Y-%m-%d %H:%M} · {row.get('type', 'sleep')} · {row['ingest']}"

    key = st.selectbox(label, list(records), format_func=readable)
    return pd.Series(records[key])


def calendar_bars(frame, title, unit):
    figure = go.Figure()
    for column in frame:
        figure.add_bar(x=frame.index, y=frame[column], name=column)
    figure.update_layout(
        title=title, xaxis_tickformat="%Y-%m-%d", yaxis_title=unit, barmode="stack", height=300
    )
    st.plotly_chart(figure, width="stretch")


def local_times(frame):
    return frame.time_utc + frame.utc_offset.map(
        {v: pd.Timedelta(minutes=parse_offset(v)) for v in frame.utc_offset.unique()}
    )


def hypnogram(session, stages):
    from healthviz.analysis.sleep import session_stages

    parts = session_stages(session, stages)
    if parts.empty:
        st.info("No stage timeline is available. Vendor totals are not a hypnogram.")
        return
    fig = go.Figure()
    offset = pd.Timedelta(minutes=parse_offset(session["utc_offset"]))
    for row in parts.to_dict("records"):
        fig.add_trace(
            go.Scatter(
                x=[
                    (row["start_utc"] + offset).tz_localize(None),
                    (row["end_utc"] + offset).tz_localize(None),
                ],
                y=[row["stage"]] * 2,
                mode="lines",
                name=row["stage"],
                line={"width": 8},
                showlegend=False,
            )
        )
    fig.update_layout(
        title="Recorded sleep stages",
        xaxis_title="Recorded local time (single session offset)",
        xaxis_tickformat="%Y-%m-%d %H:%M",
        yaxis_title="Stage",
        height=300,
    )
    st.plotly_chart(fig, width="stretch")
