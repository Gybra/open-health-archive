import hashlib
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.devices import INGESTS
from healthviz.analysis.gps import map_deck, parse_track, route_profile
from healthviz.analysis.heart import max_hr, zone_seconds
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.gpx import track_bytes
from healthviz.archive.reader import ArchiveReadError, archive_token
from healthviz.archive.validate import safe_track_path
from healthviz.archive.values import parse_offset
from healthviz.dashboard.charts import filtered, overlap_audit, raw_data
from healthviz.dashboard.context import device_names, open_page
from healthviz.dashboard.format import day_text, kcal, km, minutes_text, pace_text

PACED = ("walking", "running", "hiking")


def type_label(kind) -> str:
    return str(kind).replace("_", " ").capitalize()


def workout_filter(context):
    """Workouts in the period, narrowed by activity type and physical device."""
    tables, settings = context.tables, context.settings
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    workouts = filtered(workouts, context.start, context.end)
    names = device_names(context)
    kinds = sorted(workouts.type.unique())
    devices = sorted(workouts.physical_device_id.unique())
    types = st.multiselect("Activity types", kinds, default=kinds, format_func=type_label)
    chosen = st.multiselect(
        "Physical devices",
        devices,
        default=devices,
        format_func=lambda device: names.get(device, device),
    )
    return workouts.loc[workouts.type.isin(types) & workouts.physical_device_id.isin(chosen)].copy()


def cached_tracks(archive, paths):
    token = st.session_state["snapshot"][0][0]
    if archive_token(archive) != token:
        raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
    key = (str(archive), token)
    state = st.session_state.get("tracks")
    if state is None or state[0] != key:
        state = (key, {})
    cache = {path: entry for path, entry in state[1].items() if path in paths}
    manifest = json.loads((archive / "manifest.json").read_bytes())
    hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for path in paths:
        if path not in cache:
            try:
                if not safe_track_path(path):
                    raise ValueError
                data = track_bytes(archive / path)
                if hashlib.sha256(data).hexdigest() != hashes.get(path):
                    raise ArchiveReadError("archive: track changed; finish sync and reload")
                cache[path] = (parse_track(data), data)
            except (OSError, ValueError):
                cache[path] = (None, None)
    if archive_token(archive) != token:
        raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
    st.session_state["tracks"] = (key, cache)
    return {path: entry[0] for path, entry in cache.items()}


def resolved_hr(tables, settings):
    key = st.session_state["snapshot"][0]
    state = st.session_state.get("resolved_hr")
    if state is None or state[0] != key:
        hr, _ = resolve_rows("heart_rate", tables["heart_rate"], tables["devices"], settings)
        state = (key, hr)
        st.session_state["resolved_hr"] = state
    return state[1]


def local(row, column):
    """Wall-clock time of a UTC stamp, using the workout's own recorded offset."""
    return row[column] + pd.Timedelta(minutes=parse_offset(row["utc_offset"]))


def seconds(row) -> float:
    """Recorded active duration when present, else elapsed time between the endpoints."""
    if pd.notna(row["duration_s"]):
        return row["duration_s"]
    return (row["end_utc"] - row["start_utc"]).total_seconds()


def pace(row) -> float | None:
    """Recorded average pace for walking, running and hiking, in min/km."""
    distance = row["distance_m"]
    if row["type"] not in PACED or pd.isna(distance) or distance <= 0 or seconds(row) <= 0:
        return None
    return seconds(row) / 60 / (distance / 1000)


def workout_list(workouts, names) -> pd.DataFrame:
    rows = [
        {
            "Date": day_text(local(row, "start_utc").date()),
            "Start": f"{local(row, 'start_utc'):%H:%M}",
            "Type": type_label(row["type"]),
            "Duration": minutes_text(seconds(row) / 60),
            "Distance": "" if pd.isna(row["distance_m"]) else km(row["distance_m"]),
            "Pace": "" if pace(row) is None else pace_text(pace(row)),
            "Active energy": "" if pd.isna(row["active_kcal"]) else kcal(row["active_kcal"]),
            "Source": names.get(row["device_id"], row["device_id"]),
        }
        for row in workouts.sort_values("start_utc", ascending=False, kind="stable").to_dict(
            "records"
        )
    ]
    columns = ["Date", "Start", "Type", "Duration", "Distance", "Pace", "Active energy", "Source"]
    return pd.DataFrame(rows, columns=columns)


def pick_workout(workouts):
    records = {
        (row["ingest"], row["record_id"]): row
        for row in workouts.sort_values("start_utc", ascending=False, kind="stable").to_dict(
            "records"
        )
    }

    def readable(key):
        row = records[key]
        distance = "" if pd.isna(row["distance_m"]) else f" · {km(row['distance_m'])}"
        start = local(row, "start_utc")
        origin = INGESTS.get(row["ingest"], row["ingest"])
        return (
            f"{day_text(start.date())} {start:%H:%M} · {type_label(row['type'])}{distance}"
            f" · {origin}"
        )

    key = st.selectbox("Workout", list(records), format_func=readable, key="workout")
    return pd.Series(records[key])


def summary_numbers(workout):
    columns = st.columns(5)
    columns[0].metric("Duration", minutes_text(seconds(workout) / 60))
    columns[1].metric("Distance", "—" if pd.isna(workout.distance_m) else km(workout.distance_m))
    columns[2].metric("Pace", "—" if pace(workout) is None else pace_text(pace(workout)))
    columns[3].metric(
        "Active energy", "—" if pd.isna(workout.active_kcal) else kcal(workout.active_kcal)
    )
    columns[4].metric("Ascent", "—" if pd.isna(workout.ascent_m) else f"{workout.ascent_m:.0f} m")
    st.caption(
        "Recorded active duration"
        if pd.notna(workout.duration_s)
        else "Duration derived from the start and end times (elapsed, including pauses)"
    )
    if pd.notna(workout.ascent_m) or pd.notna(workout.descent_m):
        attribution = (
            workout.ascent_computed_by if pd.notna(workout.ascent_computed_by) else "unknown"
        )
        st.caption(f"Ascent/descent attribution: {attribution}; no external elevation lookup.")


def heart_rate(context, workout):
    """Zones and the heart-rate curve on the workout's local clock."""
    tables, settings = context.tables, context.settings
    hr = resolved_hr(tables, settings)
    samples = hr.loc[(hr.time_utc >= workout.start_utc) & (hr.time_utc < workout.end_utc)]
    maximum, method = max_hr(
        settings,
        hr,
        resolve_rows("workouts", tables["workouts"], tables["devices"], settings)[0],
        workout.date_local,
    )
    st.caption(
        f"Max HR method: {method}"
        + (f" · {maximum:.1f} bpm" if maximum else " · profile or confirmed samples needed")
    )
    zones = zone_seconds(samples, workout.start_utc, workout.end_utc, maximum)
    if not zones.empty:
        st.dataframe(
            pd.DataFrame({"Zone": zones.zone, "Time": (zones.seconds / 60).map(minutes_text)}),
            hide_index=True,
        )
    if not samples.empty:
        offset = pd.Timedelta(minutes=parse_offset(workout.utc_offset))
        times = (samples.time_utc + offset).dt.tz_localize(None)
        pulse = go.Figure(go.Scatter(x=times, y=samples.bpm, connectgaps=False))
        pulse.update_layout(
            title="Workout heart rate",
            xaxis_title="Local time",
            xaxis_tickformat="%H:%M",
            yaxis_title="bpm",
        )
        st.plotly_chart(pulse, width="stretch")
    return samples, zones


def route(context, workout, samples):
    """Map and GPS profiles; returns the profile for the raw-data section."""
    if pd.isna(workout.track_file) or not workout.track_file:
        st.info("No GPS track for this workout; recorded metrics remain available.")
        return None
    points = cached_tracks(context.archive, {workout.track_file})[workout.track_file]
    if points is None or points.empty:
        st.warning("Invalid or empty GPS track; recorded workout metrics remain available.")
        return None
    profile = route_profile(points, samples)
    coloring = st.radio("Route color", ["pace", "hr"], horizontal=True)
    st.caption(
        "Pace: preceding 30 elapsed seconds. HR: nearest selected sample within "
        "60 s. Grey means unavailable. GPS-derived distance is separate from "
        "recorded workout distance."
    )
    st.pydeck_chart(
        map_deck(profile, offline=context.offline, coloring=coloring), key="workout-route"
    )
    for metric, label in [
        ("pace_min_km", "GPS pace (min/km)"),
        ("bpm", "Matched heart rate (bpm)"),
        ("elevation_m", "GPX elevation (m)"),
    ]:
        if profile[metric].notna().any():
            fig = go.Figure(
                go.Scatter(
                    x=profile.distance_m / 1000, y=profile[metric], mode="lines", connectgaps=False
                )
            )
            fig.update_layout(
                title=label, xaxis_title="GPS-derived distance (km)", yaxis_title=label
            )
            if metric == "pace_min_km":
                fig.update_yaxes(autorange="reversed")  # faster is higher
            st.plotly_chart(fig, width="stretch")
    # Download exactly the bytes used by this validated route, not a later sync revision.
    data = st.session_state["tracks"][1][workout.track_file][1]
    st.download_button(
        "Download GPX", data, file_name=f"{workout.workout_id}.gpx", mime="application/gpx+xml"
    )
    return profile


def workout_detail(context, workout) -> dict[str, pd.DataFrame]:
    start, end = local(workout, "start_utc"), local(workout, "end_utc")
    st.subheader(f"{type_label(workout.type)} · {day_text(start.date())} {start:%H:%M}–{end:%H:%M}")
    summary_numbers(workout)
    st.button(
        "Open this day →", on_click=open_page, args=("Day",), kwargs={"day": workout.date_local}
    )
    samples, zones = heart_rate(context, workout)
    profile = route(context, workout, samples)
    frames = {"Workout detail": pd.DataFrame([workout]), "Heart rate zone durations": zones}
    if profile is not None:
        frames["GPS-derived route profile"] = profile
    return frames


def calories(workouts):
    duration = workouts.duration_s.fillna(
        (workouts.end_utc - workouts.start_utc).dt.total_seconds()
    )
    workouts = workouts.assign(
        kcal_per_min=workouts.active_kcal / (duration.where(duration > 0) / 60)
    )
    by_type = workouts.groupby("type")[["active_kcal", "total_kcal", "kcal_per_min"]].mean()
    return workouts, by_type.reset_index()


def render(context):
    workouts = workout_filter(context)
    if workouts.empty:
        st.info("No workouts match these filters.")
        return
    st.dataframe(workout_list(workouts, device_names(context)), hide_index=True)
    frames = workout_detail(context, pick_workout(workouts))
    per_workout, by_type = calories(workouts)
    raw_data(
        {
            "Filtered workouts": workouts,
            **frames,
            "Workout calories": per_workout,
            "Workout calories by type": by_type,
            "Workout source overlaps": overlap_audit(context, "workouts"),
        }
    )
