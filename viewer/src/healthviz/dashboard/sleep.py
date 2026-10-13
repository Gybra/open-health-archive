import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import (
    calendar_bars,
    filtered,
    hypnogram,
    select_record,
    show_trend,
    summary_table,
)


def render(tables, daily, settings, *, start, end):
    show_trend(daily, "sleep_min", "Main sleep duration", "min", start=start, end=end)
    sessions, _ = resolve_rows(
        "sleep_sessions", tables["sleep_sessions"], tables["devices"], settings
    )
    nights = filtered(sleep_summary(sessions, tables["sleep_stages"]), start, end)
    st.caption(
        "Longest ending session is main sleep; other sessions are naps. Unknown "
        "completeness is not verified completeness. Missing REM is not zero. Elapsed "
        "session time is not measured sleep."
    )
    summary_table(nights, "Sleep sessions and naps")
    if not nights.empty:
        main = nights.loc[nights.main].set_index("date_local")
        clock = go.Figure()
        for column, name in [("onset_wall_min", "Onset"), ("wake_wall_min", "Wake")]:
            clock.add_scatter(
                x=main.index, y=(main[column] - 1080) % 1440, name=name, connectgaps=False
            )
        clock.update_layout(
            title="Recorded onset and wake clocks",
            xaxis_tickformat="%Y-%m-%d",
            yaxis={
                "tickvals": [0, 360, 720, 1080, 1440],
                "ticktext": ["18:00", "00:00", "06:00", "12:00", "18:00"],
            },
        )
        st.plotly_chart(clock, width="stretch")
        calendar_bars(
            main[["deep_share", "light_share", "rem_share", "awake_share", "unknown_share"]],
            "Recorded stage shares",
            "fraction of known stages",
        )
        hypnogram(select_record(nights, "Sleep session").to_dict(), tables["sleep_stages"])
    for period in ("week", "month"):
        summary_table(
            period_summary(filtered(daily, start, end), period), f"Sleep {period} summaries"
        )
