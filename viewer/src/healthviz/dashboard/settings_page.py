"""Settings: profile, readable device names, associations, priorities, import status."""

from dataclasses import replace
from datetime import date

import pandas as pd
import streamlit as st

from healthviz.analysis.devices import device_labels, device_sources, suggest_duplicates
from healthviz.dashboard import overlaps
from healthviz.dashboard.context import open_page
from healthviz.dashboard.format import stamp_text
from healthviz.health_connect.status import load_status
from healthviz.settings import save_settings

STATUS_FILE = "health-connect-import.json"
METRICS = [
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
]


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


def duplicates(context) -> list[tuple[str, str]]:
    return per_snapshot("duplicates", lambda: suggest_duplicates(context.tables, context.settings))


def duplicate_notice(context) -> None:
    """Overview hint only; the owner answers in Settings, nothing is associated automatically."""
    pairs = duplicates(context)
    if not pairs:
        return
    names = device_names(context)
    listed = "; ".join(f"{names[a]} and {names[b]}" for a, b in pairs)
    st.info(
        f"{listed} report matching daily steps. If they are the same physical device, "
        "associate them in Settings so one is chosen instead of both being compared."
    )
    st.button("Review in Settings", on_click=open_page, args=("Settings",))


def answer_duplicates(context, names) -> None:
    settings = context.settings
    for a, b in duplicates(context):
        st.info(f"{names[a]} and {names[b]} report matching daily steps. Same physical device?")
        same, different = st.columns(2)
        if same.button("Same physical device", key=f"same-{a}-{b}"):
            target = settings.device_aliases.get(a, a)
            aliases = {k: target if v == b else v for k, v in settings.device_aliases.items()}
            save(context, replace(settings, device_aliases={**aliases, b: target}))
        if different.button("Not the same device", key=f"different-{a}-{b}"):
            pairs = [*settings.not_same_devices, [a, b]]
            save(context, replace(settings, not_same_devices=pairs))


def save(context, updated) -> None:
    updated.check_devices(set(context.tables["devices"].device_id))
    save_settings(context.config, updated)
    st.rerun()


def settings_form(settings, devices, config, names=None):
    names = names or {}
    metric = st.selectbox("Priority metric", METRICS)
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
            "Hours with heart-rate samples for a complete day",
            min_value=1,
            max_value=25,
            value=settings.worn_hours_threshold,
        )
        timezone = st.text_input("Fallback timezone (IANA)", settings.default_timezone)
        ids = devices.device_id.tolist()
        label = lambda device: names.get(device, device)  # noqa: E731
        order = st.multiselect(
            "Preferred devices (selection order)",
            ids,
            default=settings.priority.get(metric, []),
            key="priority-" + metric,
            format_func=label,
        )
        st.caption(
            "Defaults: watches before phones; vendor exports before Health Connect. "
            "Configure ingest order in the private TOML file."
        )
        origin = st.selectbox("Source to associate", ["None", *ids], format_func=label)
        target = st.selectbox("Same physical device as", ["None", *ids], format_func=label)
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


def import_line(path, timezone) -> str:
    """One short line for the page header; the details live in Settings."""
    status = load_status(path)
    if status is None:
        return ""
    if status.error:
        return " · Health Connect import failed (see Settings)"
    return f" · Health Connect imported {stamp_text(status.imported_at, timezone)}"


def import_status(path, timezone):
    status = load_status(path)
    if status is None:
        st.caption("No Health Connect import yet.")
        return
    folder = f" from {status.folder}" if status.folder else ""
    if status.error:
        st.error(f"Health Connect import failed{folder}: {status.error}")
    elif status.zip_name:
        st.caption(
            f"Health Connect: {status.zip_name}{folder}, imported "
            f"{stamp_text(status.imported_at, timezone)}"
        )
    last = status.last_success or {}
    if status.error and last:
        st.caption(
            f"Last successful import: {last.get('zip_name')} at "
            f"{stamp_text(last.get('imported_at'), timezone)}"
        )
    if not status.format_tested and status.format_version is not None:
        st.warning(f"Health Connect export format {status.format_version} not yet tested")
    if status.not_imported:
        listed = ", ".join(
            f"{name.replace('_', ' ')}: {count}" for name, count in status.not_imported.items()
        )
        st.caption(f"Not imported (no archive table yet): {listed}")
    if status.skipped:
        listed = ", ".join(f"{name}: {count}" for name, count in status.skipped.items())
        st.caption(f"Skipped invalid or implausible records: {listed}")


def render(context):
    names = device_names(context)
    devices = context.tables["devices"]
    st.subheader("Devices")
    st.dataframe(
        pd.DataFrame(
            {
                "Name": devices.device_id.map(names),
                "Kind": devices.kind.str.title(),
                "Vendor": devices.vendor,
                "Model": devices.model,
            }
        ),
        hide_index=True,
        width="stretch",
    )
    answer_duplicates(context, names)
    st.subheader("Profile, priorities and associations")
    settings_form(context.settings, devices, context.config, names)
    st.subheader("Health Connect import")
    import_status(context.config.parent / STATUS_FILE, context.settings.default_timezone)
    st.subheader("Source overlaps")
    overlaps.render(context)
