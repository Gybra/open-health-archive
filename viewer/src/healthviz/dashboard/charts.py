from collections.abc import Callable
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.sources import resolve_rows
from healthviz.analysis.usual import READINGS
from healthviz.archive.values import parse_offset
from healthviz.dashboard.context import per_snapshot
from healthviz.dashboard.format import difference_text, measured_text, resting_text

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


def resting_figure(daily, start, end, usual) -> go.Figure:
    """Keep the daily statistic, but distinguish supplied values from viewer estimates."""
    figure = daily_figure(daily, "resting_hr", start, end, usual, "bpm")
    if daily.empty:
        return figure
    period = filtered(daily, start, end).sort_values("date_local")
    estimated = period.resting_hr_quality.eq("derived from main sleep")
    text = [escape(resting_text(row)) for row in period.itertuples()]
    single = figure.data[0]
    points = []
    for name, mask, symbol, color in (
        ("Provided by source", ~estimated, "circle", FADED),
        ("Estimated from sleep", estimated, "diamond", AVERAGE),
    ):
        points.append(
            go.Scatter(
                x=single.x,
                y=[
                    value if keep and pd.notna(value) else None
                    for value, keep in zip(single.y, mask, strict=True)
                ],
                name=name,
                mode="markers",
                marker={"symbol": symbol, "color": color, "size": 7},
                text=text,
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:.0f} bpm<br>%{text}<extra></extra>",
            )
        )
    # Wrapped mobile legends must grow above the plot, not cover its highest readings.
    figure.update_layout(legend={"y": 1.02, "yanchor": "bottom"}, margin={"t": 80}, height=320)
    return go.Figure(data=[*points, *figure.data[1:]], layout=figure.layout)


def resting_caption(daily, start, end):
    period = filtered(daily, start, end)
    present = period.resting_hr.notna()
    missing = int((~present).sum())
    excluded = int((present & ~period.complete.astype(bool)).sum())
    st.caption(
        "Estimates require sufficient heart-rate samples during main sleep. "
        "Unavailable values do not by themselves indicate a cache error. "
        f"{missing} days unavailable · {excluded} recorded "
        f"{'day' if excluded == 1 else 'days'} excluded from daily aggregates."
    )
    methods = period.loc[present, "resting_hr_quality"].eq("derived from main sleep")
    if methods.any() and (~methods).any():
        st.caption(
            "This period mixes source-provided and viewer-estimated values; methods may differ."
        )


def range_figure(daily, start, end) -> go.Figure:
    """Lowest to highest heart rate per complete day as a band, the daily mean as a line."""
    daily = filtered(daily, start, end).sort_values("date_local")
    complete = daily.complete.astype(bool)
    figure = go.Figure()
    for column, name, fill in [("hr_min", "lowest", None), ("hr_max", "highest", "tonexty")]:
        figure.add_scatter(
            x=daily.date_local,
            y=pd.to_numeric(daily[column]).where(complete),
            name=name,
            mode="lines",
            line={"color": FADED, "width": 1},
            fill=fill,
            connectgaps=False,
        )
    figure.add_scatter(
        x=daily.date_local,
        y=pd.to_numeric(daily.hr_mean).where(complete),
        name="daily average",
        line={"color": AVERAGE, "width": 2.4},
        connectgaps=False,
    )
    return compact(figure, "bpm")


def coverage_figure(daily, start, end, threshold) -> go.Figure:
    """Hours with heart-rate samples per day; a day counts as complete from the threshold up."""
    daily = filtered(daily, start, end).sort_values("date_local")
    figure = go.Figure(
        go.Bar(x=daily.date_local, y=daily.worn_hours, name="hours measured", marker_color=FADED)
    )
    figure.add_scatter(
        x=[start, end],
        y=[threshold] * 2,
        name="complete day",
        mode="lines",
        line={"color": USUAL, "dash": "dash"},
    )
    figure.update_yaxes(range=[0, 24])
    return compact(figure, "hours")


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
    return compact(figure, "hours in bed", height=300)


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


def raw_data(frames: Callable[[], dict[str, pd.DataFrame]]) -> None:
    """The only place for UTC times, offsets and archive column names.

    Tables, audits and CSV exports are built only while the section is open.
    """
    section = st.expander("Raw data and sources", key="raw-data", on_change="rerun")
    if not section.open:
        return
    with section, st.spinner("Preparing raw data…", show_time=True):
        for title, frame in frames().items():
            summary_table(frame, title)


def overlap_audit(context, metric) -> pd.DataFrame:
    """Rows of days where several sources report the metric, or one source overlaps itself.

    Resolved once per snapshot over the whole archive; a period only filters the result.
    """

    def compute():
        tables = context.tables
        _, audit = resolve_rows(metric, tables[metric], tables["devices"], context.settings)
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

    return filtered(per_snapshot("overlaps-" + metric, compute), context.start, context.end)


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
