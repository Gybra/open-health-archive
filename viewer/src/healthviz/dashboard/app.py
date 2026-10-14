import argparse
import importlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import streamlit as st

from healthviz.analysis.apps import app_choices, select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.archive.reader import ArchiveReadError, load_archive, verify_snapshot
from healthviz.health_connect.status import load_status
from healthviz.read_model import ReadModelError, load_read_model, validate_location
from healthviz.settings import SettingsError, load_settings, save_settings

STATUS_FILE = "health-connect-import.json"
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
            order = st.multiselect(
                "Preferred devices (selection order)",
                ids,
                default=settings.priority.get(metric, []),
                key="priority-" + metric,
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


def app_filter(settings, choices, config):
    """One, several or all apps; saved like the other private settings."""
    if not choices:
        return
    current = [a for a in settings.apps if a in choices] or choices
    chosen = st.sidebar.multiselect("Apps", choices, default=current)
    if not chosen:
        st.sidebar.info("Choose at least one app.")
        return
    apps = [] if set(chosen) == set(choices) else chosen
    if apps != settings.apps and set(chosen) != set(current):
        save_settings(config, replace(settings, apps=apps))
        st.rerun()


def import_status(path):
    status = load_status(path)
    if status is None:
        return
    folder = f" from {status.folder}" if status.folder else ""
    if status.error:
        st.sidebar.error(f"Health Connect import failed{folder}: {status.error}")
    elif status.zip_name:
        st.sidebar.caption(
            f"Health Connect: {status.zip_name}{folder}, imported {status.imported_at}"
        )
    last = status.last_success or {}
    if status.error and last:
        st.sidebar.caption(
            f"Last successful import: {last.get('zip_name')} at {last.get('imported_at')}"
        )
    if not status.format_tested and status.format_version is not None:
        st.sidebar.warning(f"Health Connect export format {status.format_version} not yet tested")
    if status.not_imported:
        listed = ", ".join(
            f"{name.replace('_', ' ')}: {count}" for name, count in status.not_imported.items()
        )
        st.sidebar.caption(f"Not imported (no archive table yet): {listed}")
    if status.skipped:
        listed = ", ".join(f"{name}: {count}" for name, count in status.skipped.items())
        st.sidebar.caption(f"Skipped invalid or implausible records: {listed}")


def clear_snapshot_context():
    for key in ("snapshot", "overview_sources", "tracks", "resolved_hr", "heatmap", "app_choices"):
        st.session_state.pop(key, None)


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
    settings_form(settings, tables["devices"], args.config)
    app_filter(settings, st.session_state["app_choices"], args.config)
    import_status(args.config.parent / STATUS_FILE)
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
        format="YYYY-MM-DD",
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
    except (ArchiveReadError, SettingsError, ReadModelError) as error:
        clear_snapshot_context()
        st.error(str(error))
    except Exception:
        # Third-party exception text can include an entire row or a coordinate.
        clear_snapshot_context()
        st.error("Viewer cannot process this selection. Check archive integrity and settings.")
