import streamlit as st

from healthviz.analysis.usual import compare_daily
from healthviz.dashboard.charts import daily_figure


def render(context):
    usual = compare_daily(context.daily, "resting_hr", context.start, context.end).usual
    st.plotly_chart(
        daily_figure(context.daily, "resting_hr", context.start, context.end, usual, "bpm"),
        width="stretch",
    )
