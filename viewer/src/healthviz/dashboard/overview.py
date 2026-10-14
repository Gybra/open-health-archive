import streamlit as st

from healthviz.analysis.daily import period_summary
from healthviz.analysis.observations import observations
from healthviz.dashboard.charts import calendar_bars, filtered, show_trend, summary_table
from healthviz.dashboard.context import derived


def render(context):
    daily, start, end = context.daily, context.start, context.end
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
    sleep, workouts = derived(context)
    st.subheader("Personal-baseline observations")
    messages = observations(daily, sleep, workouts, end)
    if not messages:
        st.info("Not enough eligible history for a baseline comparison, or no observations.")
    for message in messages:
        st.text(message, width="stretch")
    summary_table(frame, "Daily overview")
