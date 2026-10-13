import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.observations import observations
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import calendar_bars, filtered, show_trend, summary_table


def render(tables, daily, settings, *, start, end):
    frame = filtered(daily, start, end)
    for metric, title, unit in [
        ("resting_hr", "Resting heart rate", "bpm"),
        ("sleep_min", "Main sleep duration", "min"),
        ("steps", "Daily steps", "count"),
        ("active_kcal", "Active calories", "kcal"),
    ]:
        show_trend(daily, metric, title, unit, start=start, end=end)
    weeks = period_summary(frame, "week")
    calendar_bars(weeks.set_index("period")[["workout_min"]], "Weekly workout minutes", "min")
    st.caption(
        "Workout minutes use recorded active duration where available, otherwise "
        "elapsed UTC endpoints; overnight allocation is proportional."
    )
    calendar_bars(
        frame.set_index("date_local")[["worn_hours"]],
        "Coverage · local hours with HR samples",
        "hours with samples",
    )
    key = st.session_state["snapshot"][0]
    context = st.session_state.get("overview_sources")
    if context is None or context[0] != key:
        sessions, _ = resolve_rows(
            "sleep_sessions", tables["sleep_sessions"], tables["devices"], settings
        )
        workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
        context = (key, sleep_summary(sessions, tables["sleep_stages"]), workouts)
        st.session_state["overview_sources"] = context
    _, sleep, workouts = context
    st.subheader("Personal-baseline observations")
    messages = observations(daily, sleep, workouts, end)
    if not messages:
        st.info("Not enough eligible history for a baseline comparison, or no observations.")
    for message in messages:
        st.text(message, width="stretch")
    summary_table(frame, "Daily overview")
