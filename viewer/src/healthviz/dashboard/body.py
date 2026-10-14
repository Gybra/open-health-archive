import streamlit as st

from healthviz.dashboard.charts import daily_figure


def render(context):
    st.plotly_chart(
        daily_figure(context.daily, "weight", context.start, context.end, None, "kg"),
        width="stretch",
    )
