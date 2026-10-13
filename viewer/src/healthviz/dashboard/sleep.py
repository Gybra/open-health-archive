import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import filtered, hypnogram, show_trend, summary_table


def render(tables, daily, settings, *, start, end):
    show_trend(filtered(daily, start, end), "sleep_min", "Main sleep duration", "min")
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
        st.line_chart(
            nights.loc[nights.main].set_index("date_local")[["onset_wall_min", "wake_wall_min"]]
        )
        st.bar_chart(
            nights.loc[nights.main].set_index("date_local")[
                ["deep_share", "light_share", "rem_share", "awake_share", "unknown_share"]
            ]
        )
        choice = st.selectbox("Sleep session", nights.session_id.tolist())
        hypnogram(nights.loc[nights.session_id == choice].iloc[0].to_dict(), tables["sleep_stages"])
    for period in ("week", "month"):
        summary_table(
            period_summary(filtered(daily, start, end), period), f"Sleep {period} summaries"
        )
