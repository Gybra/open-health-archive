import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from healthviz.analysis.gps import map_deck, read_track, route_profile
from healthviz.analysis.heart import max_hr, zone_seconds
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.gpx import track_bytes, validate_gpx
from healthviz.archive.reader import archive_token
from healthviz.dashboard.charts import filtered, summary_table


def workout_filter(tables, settings, start, end):
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    workouts = filtered(workouts, start, end)
    types = st.multiselect(
        "Activity types", sorted(workouts.type.unique()), default=sorted(workouts.type.unique())
    )
    devices = st.multiselect(
        "Physical devices",
        sorted(workouts.physical_device_id.unique()),
        default=sorted(workouts.physical_device_id.unique()),
    )
    return workouts.loc[
        workouts.type.isin(types) & workouts.physical_device_id.isin(devices)
    ].copy()


def cached_tracks(archive, paths):
    key = (str(archive), archive_token(archive))
    state = st.session_state.get("tracks")
    if state is None or state[0] != key:
        state = (key, {})
    cache = {path: points for path, points in state[1].items() if path in paths}
    for path in paths:
        if path not in cache:
            try:
                cache[path] = read_track(archive, path)
            except ValueError:
                cache[path] = None
    st.session_state["tracks"] = (key, cache)
    return cache


def resolved_hr(tables, settings):
    key = st.session_state["snapshot"][0]
    state = st.session_state.get("resolved_hr")
    if state is None or state[0] != key:
        hr, _ = resolve_rows("heart_rate", tables["heart_rate"], tables["devices"], settings)
        state = (key, hr)
        st.session_state["resolved_hr"] = state
    return state[1]


def render(tables, daily, settings, *, start, end, archive, offline):
    workouts = workout_filter(tables, settings, start, end)
    summary_table(workouts, "Filtered workouts")
    if workouts.empty:
        st.info("No workouts match these filters.")
        return
    choice = st.selectbox("Workout", workouts.workout_id.tolist(), format_func=lambda key: key)
    workout = workouts.loc[workouts.workout_id == choice].iloc[0]
    summary_table(pd.DataFrame([workout]), "Workout detail")
    duration = (
        workout.duration_s
        if pd.notna(workout.duration_s)
        else (workout.end_utc - workout.start_utc).total_seconds()
    )
    st.caption(
        "Recorded active duration"
        if pd.notna(workout.duration_s)
        else "Duration derived from UTC endpoints (elapsed, including pauses)"
    )
    if (
        pd.notna(workout.distance_m)
        and workout.distance_m > 0
        and duration > 0
        and workout.type in ("walking", "running", "hiking")
    ):
        st.write(f"Recorded average pace: {duration / 60 / (workout.distance_m / 1000):.2f} min/km")
    if pd.notna(workout.ascent_m) or pd.notna(workout.descent_m):
        st.caption(
            f"Ascent/descent attribution: {workout.ascent_computed_by or 'unknown'}; "
            f"no external elevation lookup."
        )
    hr = resolved_hr(tables, settings)
    samples = hr.loc[(hr.time_utc >= workout.start_utc) & (hr.time_utc < workout.end_utc)]
    maximum, method = max_hr(
        settings,
        hr,
        resolve_rows("workouts", tables["workouts"], tables["devices"], settings)[0],
        workout.date_local,
    )
    st.write(
        f"Max HR method: {method}"
        + (f" · {maximum:.1f} bpm" if maximum else " · profile or confirmed samples needed")
    )
    zones = zone_seconds(samples, workout.start_utc, workout.end_utc, maximum)
    summary_table(zones, "Heart rate zone durations")
    if not samples.empty:
        st.line_chart(samples.set_index("time_utc")[["bpm"]])
    if pd.isna(workout.track_file) or not workout.track_file:
        st.info("No GPS track for this workout; recorded metrics remain available.")
        return
    points = cached_tracks(archive, {workout.track_file})[workout.track_file]
    if points is None or points.empty:
        st.warning("Invalid or empty GPS track; recorded workout metrics remain available.")
        return
    profile = route_profile(points, samples)
    coloring = st.radio("Route color", ["pace", "hr"], horizontal=True)
    st.caption(
        "Pace: preceding 30 elapsed seconds. HR: nearest selected sample within "
        "60 s. Grey means unavailable. GPS-derived distance is separate from "
        "recorded workout distance."
    )
    st.pydeck_chart(map_deck(profile, offline=offline, coloring=coloring), key="workout-route")
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
            st.plotly_chart(fig, width="stretch")
    summary_table(profile, "GPS-derived route profile")
    data = track_bytes(archive / workout.track_file)
    validate_gpx(data)
    st.download_button(
        "Download GPX", data, file_name=f"{workout.workout_id}.gpx", mime="application/gpx+xml"
    )
