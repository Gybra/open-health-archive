import argparse
import importlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import streamlit as st

from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import ArchiveReadError, archive_token, load_archive
from healthviz.settings import SettingsError, load_settings, save_settings

PAGES = {
    "Overview": "overview",
    "Sleep": "sleep",
    "Activity & calories": "activity",
    "Workouts": "workouts",
    "Map": "maps",
    "Day": "day",
    "Overlaps": "overlaps",
}


def settings_form(settings, devices, config):
    with st.sidebar.expander("Personal settings and source priorities"):
        with st.form("settings"):
            birth = st.number_input(
                "Birth year (0 = unknown)",
                min_value=0,
                max_value=date.today().year,
                value=settings.birth_year or 0,
            )
            maximum = st.number_input(
                "Max HR (0 = derive)", min_value=0.0, value=float(settings.max_hr or 0)
            )
            threshold = st.number_input(
                "HR sample-hours threshold",
                min_value=1,
                max_value=25,
                value=settings.worn_hours_threshold,
            )
            timezone = st.text_input("Fallback timezone (IANA)", settings.default_timezone)
            ids = devices.device_id.tolist()
            metric = st.selectbox(
                "Priority metric",
                [
                    "heart_rate",
                    "steps",
                    "distance",
                    "active_kcal",
                    "total_kcal",
                    "sleep_sessions",
                    "workouts",
                    "resting_heart_rate",
                    "weight",
                    "spo2",
                ],
            )
            order = st.multiselect(
                "Preferred devices (selection order)",
                ids,
                default=settings.priority.get(metric, []),
            )
            st.caption(
                "Defaults: watches before phones; vendor exports before Health Connect. "
                "Configure ingest order in the private TOML file."
            )
            origin = st.selectbox("Source to associate", ["None", *ids])
            target = st.selectbox("Same physical device as", ["None", *ids])
            st.caption(
                "Associate only sources you know describe the same physical device; names "
                "are not proof. Never guess the device of unattributed summaries."
            )
            submitted = st.form_submit_button("Save private settings")
        if submitted:
            aliases = dict(settings.device_aliases)
            if origin != "None" and target != "None":
                aliases[origin] = target
            updated = replace(
                settings,
                birth_year=birth or None,
                max_hr=maximum or None,
                worn_hours_threshold=threshold,
                default_timezone=timezone,
                priority={**settings.priority, metric: order},
                device_aliases=aliases,
            )
            updated.check_devices(set(ids))
            save_settings(config, updated)
            st.rerun()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".config/healthviz/config.toml"
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    st.set_page_config(page_title="Open Health Archive", layout="wide")
    st.set_option("client.showErrorDetails", "none")
    st.title("Open Health Archive")
    st.caption(
        "Local, vendor-neutral history · Not a medical device. No diagnosis or "
        "medical advice. Cloud providers can read plaintext archives."
    )
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
    token = archive_token(archive)
    key = (token, settings)
    cache = st.session_state.get("snapshot")
    if cache is None or cache[0] != key:
        with st.spinner("Validating archive and resolving sources…"):
            tables = load_archive(archive)
            settings.check_devices(set(tables["devices"].device_id))
            daily = daily_summary(tables, tables["devices"], settings)
            st.session_state["snapshot"] = (key, tables, daily)
    _, tables, daily = st.session_state["snapshot"]
    if tables["devices"].vendor.fillna("").eq("Fictional").all() and not tables["devices"].empty:
        st.info("Synthetic demonstration archive — not personal measurements.")
    settings_form(settings, tables["devices"], args.config)
    page = st.sidebar.selectbox("Page", list(PAGES), key="page")
    st.sidebar.caption(
        "Offline: no basemap requests"
        if args.offline
        else "Online maps: OSM tiles disclose the viewed area to the tile provider."
    )
    if daily.empty:
        st.info("Archive has no observations.")
        return
    dates = st.sidebar.date_input(
        "Period",
        value=(daily.date_local.min(), daily.date_local.max()),
        min_value=daily.date_local.min(),
        max_value=daily.date_local.max(),
    )
    if len(dates) != 2:
        st.info("Choose the start and end dates.")
        return
    start, end = dates
    module = importlib.import_module("healthviz.dashboard." + PAGES[page])
    st.header(page)
    kwargs = {"archive": archive, "offline": args.offline} if page in ("Workouts", "Map") else {}
    module.render(tables, daily, settings, start=start, end=end, **kwargs)


if __name__ == "__main__":
    try:
        main()
    except (ArchiveReadError, SettingsError) as error:
        st.session_state.pop("snapshot", None)
        st.error(str(error))
    except Exception:
        # Third-party exception text can include an entire row or a coordinate.
        st.session_state.pop("snapshot", None)
        st.error("Viewer cannot process this selection. Check archive integrity and settings.")
