"""What every dashboard page receives, and how pages open each other."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.settings import Settings

PAGES = {
    "Overview": "overview",
    "Sleep": "sleep",
    "Heart": "heart",
    "Activity": "activity",
    "Body": "body",
    "Settings": "settings_page",
}


@dataclass(frozen=True)
class PageContext:
    tables: dict[str, pd.DataFrame]
    daily: pd.DataFrame
    settings: Settings
    start: date
    end: date
    archive: Path
    offline: bool
    config: Path


def open_page(name: str, **state) -> None:
    """Button callback: callbacks run before widgets exist, so the page radio may change.

    "Day" is not in the sidebar; it is a view reached from lists and charts.
    """
    if name == "Day":
        st.session_state["view"] = "Day"
    else:
        st.session_state["page"] = name
        st.session_state.pop("view", None)
    st.session_state.update(state)


def derived(context: PageContext) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resolved nights and workouts, once per snapshot; the read model fills them up front."""
    key = st.session_state["snapshot"][0]
    cached = st.session_state.get("overview_sources")
    if cached is None or cached[0] != key:
        tables, devices = context.tables, context.tables["devices"]
        sessions, _ = resolve_rows(
            "sleep_sessions", tables["sleep_sessions"], devices, context.settings
        )
        workouts, _ = resolve_rows("workouts", tables["workouts"], devices, context.settings)
        cached = (key, sleep_summary(sessions, tables["sleep_stages"]), workouts)
        st.session_state["overview_sources"] = cached
    return cached[1], cached[2]
