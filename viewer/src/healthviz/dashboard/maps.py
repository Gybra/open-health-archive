from datetime import timedelta

import pandas as pd
import streamlit as st

from healthviz.analysis.gps import map_deck, route_segments
from healthviz.dashboard.charts import summary_table
from healthviz.dashboard.workouts import cached_tracks, workout_filter


def render(tables, daily, settings, *, start, end, archive, offline):
    workouts = workout_filter(tables, settings, start, end)
    reliable = workouts.loc[workouts.quality != "ambiguous"].copy()
    if len(reliable) != len(workouts):
        st.info(
            "Ambiguous same-source overlapping workouts are excluded from map density and totals."
        )
    paths = set(reliable.track_file.dropna()) - {""}
    key = (st.session_state["snapshot"][0], frozenset(paths), offline)
    context = st.session_state.get("heatmap")
    if context is None or context[0] != key:
        tracks = cached_tracks(archive, paths)
        parts = []
        for path, points in tracks.items():
            if points is None or points.empty:
                continue
            profile = points.assign(route_segment=route_segments(points))
            profile["route_segment"] = str(path) + ":" + profile.route_segment.astype(str)
            parts.append(profile)
        deck = (
            map_deck(pd.concat(parts, ignore_index=True), offline=offline, coloring="density")
            if parts
            else None
        )
        context = (key, deck)
        st.session_state["heatmap"] = context
    _, deck = context
    if deck is None:
        st.info("No valid tracks match these filters.")
    else:
        st.pydeck_chart(deck, key="archive-heatmap")
        st.caption(
            "Route density: one point every 25 m, not GPS sampling frequency. "
            "Separate tracks and gaps are never connected. OSM attribution applies "
            "to online basemaps."
        )
    reliable["distance_km"] = reliable.distance_m / 1000
    reliable["recorded_minutes"] = (
        reliable.duration_s.fillna((reliable.end_utc - reliable.start_utc).dt.total_seconds()) / 60
    )
    for period in ("week", "month"):
        reliable["period"] = reliable.date_local.map(
            lambda d, period=period: (
                d - timedelta(days=d.weekday()) if period == "week" else d.replace(day=1)
            )
        )
        totals = (
            reliable.groupby(["period", "type"])[
                ["distance_km", "recorded_minutes", "ascent_m", "descent_m"]
            ]
            .sum(min_count=1)
            .reset_index()
        )
        summary_table(totals, f"Route {period} totals by type")
