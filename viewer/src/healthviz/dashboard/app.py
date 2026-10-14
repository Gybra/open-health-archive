import argparse
import importlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import streamlit as st

from healthviz.analysis.apps import app_choices, select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import ArchiveReadError, load_archive, verify_snapshot
from healthviz.dashboard.context import PAGES, PageContext
from healthviz.dashboard.format import day_text
from healthviz.dashboard.settings_page import STATUS_FILE, duplicate_notice, import_line
from healthviz.read_model import ReadModelError, load_read_model, validate_location
from healthviz.settings import SettingsError, load_settings, save_settings


def app_filter(settings, choices, config):
    """One, several or all apps; saved like the other private settings."""
    if not choices:
        return
    current = [a for a in settings.apps if a in choices] or choices
    chosen = st.multiselect("Apps", choices, default=current)
    if not chosen:
        st.info("Choose at least one app.")
        return
    apps = [] if set(chosen) == set(choices) else chosen
    if apps != settings.apps and set(chosen) != set(current):
        save_settings(config, replace(settings, apps=apps))
        st.rerun()


def clear_snapshot_context():
    for key in (
        "snapshot",
        "overview_sources",
        "tracks",
        "resolved_hr",
        "heatmap",
        "app_choices",
        "device_names",
        "duplicates",
    ):
        st.session_state.pop(key, None)
    for key in [k for k in st.session_state if str(k).startswith("overlaps-")]:
        st.session_state.pop(key, None)


PRESETS = {"7d": 7, "30d": 30, "90d": 90, "1y": 365, "All": None, "Custom": None}


def keep_navigation_state(daily):
    """Pages without the period bar must not reset it: Streamlit drops unrendered widget state."""
    first, last = daily.date_local.min(), daily.date_local.max()
    state = st.session_state
    state.setdefault("preset", "30d")
    period = state.get("period")
    # A single date is a range being picked; keep it until the second click.
    if not period or any(day < first or day > last for day in period):
        state["period"] = (first, last)
    for key in ("preset", "period"):
        state[key] = state[key]


def period_bar(daily):
    """Period shortcuts end at the last day with data; Custom opens a date range."""
    first, last = daily.date_local.min(), daily.date_local.max()
    preset = st.segmented_control("Period", list(PRESETS), key="preset") or "30d"
    if preset == "All":
        return first, last
    if preset != "Custom":
        return last - timedelta(days=PRESETS[preset] - 1), last
    dates = st.date_input(
        "Custom period", key="period", format="YYYY-MM-DD", min_value=first, max_value=last
    )
    if len(dates) != 2:
        st.info("Choose the start and end dates.")
        return None
    return dates


ICONS = {
    "Overview": "dashboard",
    "Sleep": "bedtime",
    "Heart": "favorite",
    "Activity": "directions_run",
    "Body": "monitor_weight",
    "Settings": "settings",
}


def menu(render):
    """Sidebar menu links with their own URLs; a button's page request switches here."""
    pages = {
        name: st.Page(
            render,
            title=name,
            icon=f":material/{ICONS[name]}:",
            url_path=module.removesuffix("_page"),
            default=name == "Overview",
        )
        for name, module in PAGES.items()
    }
    current = st.navigation({"Open Health Archive": list(pages.values())})
    goto = st.session_state.pop("goto", None)
    if goto and goto != current.title:
        st.switch_page(pages[goto])
    if st.session_state.get("shown_page") != current.title:
        st.session_state.pop("view", None)
    st.session_state["shown_page"] = current.title
    return current


def top_bar(daily, settings, choices, config):
    """Period and apps apply to every page; the header says how fresh the data is."""
    left, right = st.columns([3, 2])
    with left:
        period = period_bar(daily)
    with right:
        app_filter(settings, choices, config)
    if period is not None:
        status = import_line(config.parent / STATUS_FILE, settings.default_timezone)
        st.caption(
            f"{day_text(period[0])} – {day_text(period[1])} · data up to "
            f"{day_text(daily.date_local.max())}{status}"
        )
    return period


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".config/healthviz/config.toml"
    )
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    st.set_page_config(page_title="Open Health Archive", layout="wide")
    st.set_option("client.showErrorDetails", "none")
    settings = load_settings(args.config)
    archive = args.archive or (Path(settings.archive_dir) if settings.archive_dir else None)
    if archive is None:
        st.info(
            "Select a local archive using healthviz view ARCHIVE. In Docker, set "
            "HEALTHVIZ_ARCHIVE_DIR. No directories are scanned automatically."
        )
        return
    if args.config.resolve().is_relative_to(archive.resolve()):
        raise SettingsError("config: use a location outside the archive")
    if args.cache_dir is not None:
        validate_location(args.cache_dir, archive, args.config)
        st.caption("Persistent local read model enabled · disposable plaintext copy.")
    snapshot = verify_snapshot(archive)
    key = (snapshot[0], settings)
    cache = st.session_state.get("snapshot")
    if cache is None or cache[0] != key:
        with st.spinner("Validating archive and preparing local read model…"):
            if args.cache_dir is not None:
                model = load_read_model(
                    archive, settings, cache_dir=args.cache_dir, config=args.config
                )
                everything, daily = model.tables, model.daily
                tables = select_apps(everything, settings.apps)
                context = (key, model.sleep, model.workouts)
            else:
                everything = load_archive(archive)
                settings.check_devices(set(everything["devices"].device_id))
                tables = select_apps(everything, settings.apps)
                daily = daily_summary(tables, tables["devices"], settings)
                context = None
            if verify_snapshot(archive) != snapshot:
                raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
            clear_snapshot_context()
            st.session_state["snapshot"] = (key, tables, daily)
            st.session_state["app_choices"] = app_choices(everything)
            if context is not None:
                st.session_state["overview_sources"] = context
    _, tables, daily = st.session_state["snapshot"]
    if tables["devices"].vendor.fillna("").eq("Fictional").all() and not tables["devices"].empty:
        st.info("Synthetic demonstration archive — not personal measurements.")
    shown = {}

    def render_page():
        importlib.import_module("healthviz.dashboard." + shown["module"]).render(shown["context"])

    current = menu(render_page)
    page = current.title
    st.sidebar.caption(
        "Local, vendor-neutral history · Not a medical device. No diagnosis or medical advice. "
        "Cloud providers can read plaintext archives."
    )
    st.sidebar.caption(
        "Offline: no basemap requests"
        if args.offline
        else "Online maps: OSM tiles disclose the viewed area to the tile provider."
    )
    if daily.empty:
        st.info("Archive has no observations.")
        return
    keep_navigation_state(daily)
    start, end = daily.date_local.min(), daily.date_local.max()
    view = st.session_state.get("view") if page != "Settings" else None
    st.header("Day" if view == "Day" else page)
    if page != "Settings":
        period = top_bar(daily, settings, st.session_state["app_choices"], args.config)
        if period is None:
            return
        start, end = period
    context = PageContext(tables, daily, settings, start, end, archive, args.offline, args.config)
    if page == "Overview" and view is None:
        duplicate_notice(context)
    shown.update(module="day" if view == "Day" else PAGES[page], context=context)
    current.run()


if __name__ == "__main__":
    try:
        main()
    except (ArchiveReadError, SettingsError, ReadModelError) as error:
        clear_snapshot_context()
        st.error(str(error))
    except Exception:
        # Third-party exception text can include an entire row or a coordinate.
        clear_snapshot_context()
        st.error("Viewer cannot process this selection. Check archive integrity and settings.")
