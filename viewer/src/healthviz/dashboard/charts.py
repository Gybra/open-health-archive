import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.archive.values import parse_offset


def filtered(frame, start, end):
    return (
        frame.loc[(frame.date_local >= start) & (frame.date_local <= end)].copy()
        if "date_local" in frame
        else frame.iloc[:0].copy()
    )


def trend(frame: pd.DataFrame, metric: str, title: str, unit: str) -> go.Figure:
    figure = go.Figure()
    if frame.empty:
        figure.update_layout(title=title, yaxis_title=unit)
        return figure
    frame = frame.sort_values("date_local")
    eligible = frame.sleep_eligible if metric == "sleep_min" else frame.complete
    value = pd.to_numeric(frame[metric]).where(eligible)
    figure.add_trace(
        go.Scatter(
            x=frame.date_local, y=value, name="Daily", mode="lines+markers", connectgaps=False
        )
    )
    partial = frame.loc[~eligible & frame[metric].notna()]
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
        mean = indexed.rolling(f"{window}D", min_periods=minimum).mean().where(eligible.to_numpy())
        figure.add_trace(
            go.Scatter(x=frame.date_local, y=mean, name=f"{window}-day mean", connectgaps=False)
        )
    source_cols = [f"{metric}_physical_device_id", f"{metric}_computed_by"]
    if set(source_cols).issubset(frame.columns):
        previous = None
        for row in frame.loc[frame[metric].notna()].to_dict("records"):
            key = tuple(row[c] for c in source_cols)
            if previous is not None and key != previous:
                figure.add_vline(
                    x=row["date_local"].isoformat(), line_dash="dash", line_color="#777"
                )
            previous = key
    figure.update_layout(
        title=title,
        xaxis_title="Local date",
        yaxis_title=unit,
        legend={"orientation": "h"},
        height=340,
    )
    return figure


def summary_table(frame: pd.DataFrame, title: str) -> None:
    st.subheader(title)
    st.dataframe(frame, hide_index=True, width="stretch")
    # Escaping spreadsheet formulas changes exported text only, not archived values.
    export = frame.copy()
    for col in export.select_dtypes(include=["string", "object"]):
        export[col] = export[col].map(
            lambda v: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
        )
    st.download_button(
        "Download CSV",
        export.to_csv(index=False).encode(),
        file_name=title.lower().replace(" ", "-") + ".csv",
        mime="text/csv",
        key="csv-" + title,
    )


def show_trend(frame, metric, title, unit):
    st.plotly_chart(trend(frame, metric, title, unit), width="stretch", key="trend-" + metric)


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
        yaxis_title="Stage",
        height=300,
    )
    st.plotly_chart(fig, width="stretch")
