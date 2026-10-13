import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.observations import observations
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import filtered, show_trend, summary_table


def render(tables, daily, settings, *, start, end):
    frame = filtered(daily, start, end)
    for metric, title, unit in [
        ("resting_hr", "Resting heart rate", "bpm"),
        ("sleep_min", "Main sleep duration", "min"),
        ("steps", "Daily steps", "count"),
        ("active_kcal", "Active calories", "kcal"),
    ]:
        show_trend(frame, metric, title, unit)
    weeks = period_summary(frame, "week")
    st.subheader("Weekly recorded workout minutes")
    st.bar_chart(weeks.set_index("period")[["workout_min"]] if not weeks.empty else weeks)
    st.subheader("Coverage · local hours with HR samples")
    st.bar_chart(frame.set_index("date_local")[["worn_hours"]])
    sessions, _ = resolve_rows(
        "sleep_sessions", tables["sleep_sessions"], tables["devices"], settings
    )
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    sleep = sleep_summary(sessions, tables["sleep_stages"])
    st.subheader("Personal-baseline observations")
    messages = observations(daily, sleep, workouts, end)
    if not messages:
        st.info("Not enough eligible history for a baseline comparison, or no observations.")
    for message in messages:
        st.write(message)
    summary_table(frame, "Daily overview")
