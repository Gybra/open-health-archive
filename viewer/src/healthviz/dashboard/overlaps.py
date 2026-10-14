import streamlit as st

from healthviz.dashboard.charts import overlap_audit, summary_table


def render(context):
    metric = st.selectbox(
        "Metric",
        [
            "heart_rate",
            "steps",
            "distance",
            "calories",
            "sleep_sessions",
            "workouts",
            "resting_heart_rate",
            "weight",
            "spo2",
        ],
    )
    audit = overlap_audit(context, metric)
    st.caption(
        "Original source values are compared, never added. Priority chooses one "
        "source per local hour, overlapping session or local day. Lower-priority "
        "gaps do not fill a winning hour."
    )
    summary_table(audit, "Source overlaps and resolution")
