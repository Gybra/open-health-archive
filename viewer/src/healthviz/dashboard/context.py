"""What every dashboard page receives, and how pages open each other."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from healthviz.analysis.devices import device_labels, device_sources
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


def day_picker(context: PageContext, name: str) -> None:
    """Open any day of the period, also one without a night or a workout."""
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    day = left.date_input(
        "Day",
        value=context.end,
        min_value=context.start,
        max_value=context.end,
        format="YYYY-MM-DD",
        key="pick-" + name,
    )
    right.button(
        "Open day →", on_click=open_page, args=("Day",), kwargs={"day": day}, key="open-" + name
    )


def restore(key: str, options) -> None:
    """Bring back a pick Streamlit dropped while its widget was hidden (the Day view)."""
    saved = st.session_state.get("saved-" + key)
    if key not in st.session_state and saved is not None and saved in list(options):
        st.session_state[key] = saved


def remember(key: str, value) -> None:
    st.session_state["saved-" + key] = value


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


def per_snapshot(name, compute):
    """Keep a derived value for the current snapshot (archive and settings)."""
    key = st.session_state["snapshot"][0]
    cached = st.session_state.get(name)
    if cached is None or cached[0] != key:
        cached = (key, compute())
        st.session_state[name] = cached
    return cached[1]


def device_names(context) -> dict[str, str]:
    devices = context.tables["devices"]

    return per_snapshot(
        "device_names", lambda: device_labels(devices, device_sources(context.tables))
    )
