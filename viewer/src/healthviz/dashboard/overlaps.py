import streamlit as st

from healthviz.analysis.sources import resolve_rows
from healthviz.dashboard.charts import filtered, summary_table


def render(tables, daily, settings, *, start, end):
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
    _, audit = resolve_rows(metric, tables[metric], tables["devices"], settings)
    audit = filtered(audit, start, end)
    if not audit.empty:
        sources = (
            audit[["date_local", "device_id", "ingest", "source_app"]]
            .drop_duplicates()
            .groupby("date_local")
            .size()
        )
        audit = audit.loc[
            audit.date_local.isin(sources.loc[sources > 1].index) | audit.quality.eq("ambiguous")
        ]
    st.caption(
        "Original source values are compared, never added. Priority chooses one "
        "source per local hour, overlapping session or local day. Lower-priority "
        "gaps do not fill a winning hour."
    )
    summary_table(audit, "Source overlaps and resolution")
