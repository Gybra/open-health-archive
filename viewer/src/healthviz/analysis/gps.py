import math
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pydeck as pdk

from healthviz.archive.gpx import track_bytes, validate_gpx
from healthviz.archive.validate import safe_track_path


def read_track(archive: Path, relative_path: str) -> pd.DataFrame:
    try:
        if (
            not safe_track_path(relative_path)
            or archive.is_symlink()
            or (archive / "tracks").is_symlink()
        ):
            raise ValueError
        data = track_bytes(archive / relative_path)
        validate_gpx(data)
        root = ET.fromstring(data)
        output = []
        for segment, part in enumerate(root.findall(".//{*}trkseg")):
            for point in part.findall("{*}trkpt"):
                lat, lon = float(point.attrib["lat"]), float(point.attrib["lon"])
                if (
                    not math.isfinite(lat)
                    or not math.isfinite(lon)
                    or not -90 <= lat <= 90
                    or not -180 <= lon <= 180
                ):
                    raise ValueError
                time_node = point.find("{*}time")
                time = None
                if time_node is not None and time_node.text:
                    time = datetime.fromisoformat(time_node.text.replace("Z", "+00:00"))
                    if time.tzinfo is None:
                        raise ValueError
                    time = time.astimezone(UTC)
                elevation_node = point.find("{*}ele")
                elevation = (
                    float(elevation_node.text)
                    if elevation_node is not None and elevation_node.text
                    else None
                )
                if elevation is not None and not math.isfinite(elevation):
                    raise ValueError
                output.append(
                    {
                        "segment": segment,
                        "lat": lat,
                        "lon": lon,
                        "time": time,
                        "elevation_m": elevation,
                    }
                )
        frame = pd.DataFrame(output, columns=["segment", "lat", "lon", "time", "elevation_m"])
        frame["time"] = pd.to_datetime(frame.time, utc=True)
        return frame
    except (OSError, ValueError, KeyError, ET.ParseError, OverflowError):
        raise ValueError("track: invalid or unavailable GPX") from None


def haversine(a, b):
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b["lon"] - a["lon"])
    distance = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(min(1, distance)))


def route_profile(points: pd.DataFrame, hr: pd.DataFrame) -> pd.DataFrame:
    records = points.to_dict("records")
    distance = 0.0
    run = 0
    history = []
    previous = None
    for row in records:
        gap = (
            None
            if previous is None or pd.isna(row["time"]) or pd.isna(previous["time"])
            else (row["time"] - previous["time"]).total_seconds()
        )
        connected = (
            previous is not None
            and row["segment"] == previous["segment"]
            and (gap is None or 0 < gap <= 120)
        )
        if connected:
            distance += haversine(previous, row)
        if not connected or gap is None:
            run += 1
            history = []
        row["route_segment"] = run
        row["distance_m"] = distance
        row["pace_min_km"] = None
        if pd.notna(row["time"]):
            cutoff = row["time"] - pd.Timedelta(seconds=30)
            if history and history[0][0] <= cutoff:
                while len(history) > 1 and history[1][0] <= cutoff:
                    history.pop(0)
                base_time, base_distance = history[0]
                if len(history) > 1 and base_time < cutoff:
                    later_time, later_distance = history[1]
                    fraction = (cutoff - base_time).total_seconds() / (
                        later_time - base_time
                    ).total_seconds()
                    base_distance += (later_distance - base_distance) * fraction
                delta = distance - base_distance
                if delta > 0:
                    row["pace_min_km"] = 0.5 / (delta / 1000)
            history.append((row["time"], distance))
        previous = row
    frame = pd.DataFrame(
        records, columns=[*points.columns, "route_segment", "distance_m", "pace_min_km"]
    )
    frame["bpm"] = float("nan")
    frame["elapsed_s"] = (
        (frame.time - frame.time.dropna().iloc[0]).dt.total_seconds()
        if frame.time.notna().any()
        else float("nan")
    )
    if not hr.empty and frame.time.notna().any():
        timed = frame.loc[frame.time.notna()].reset_index(names="_index")
        joined = pd.merge_asof(
            timed.sort_values("time"),
            hr[["time_utc", "bpm"]].sort_values("time_utc"),
            left_on="time",
            right_on="time_utc",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=60),
            suffixes=("_old", ""),
        )
        frame.loc[joined["_index"], "bpm"] = joined.bpm.to_numpy()
    return frame


def density_points(points):
    kept = []
    previous = None
    carried = 0.0
    segment = None
    for row in points.to_dict("records"):
        current = row.get("route_segment", row["segment"])
        if current != segment:
            kept.append(row)
            previous = row
            carried = 0.0
            segment = current
            continue
        length = haversine(previous, row)
        consumed = 0.0
        while carried + length - consumed >= 25:
            consumed += 25 - carried
            fraction = consumed / length
            kept.append(
                {
                    **row,
                    "lat": previous["lat"] + (row["lat"] - previous["lat"]) * fraction,
                    "lon": previous["lon"] + (row["lon"] - previous["lon"]) * fraction,
                }
            )
            carried = 0.0
        carried += length - consumed
        previous = row
    return pd.DataFrame(kept, columns=points.columns)


def map_deck(points: pd.DataFrame, *, offline: bool, coloring: str) -> pdk.Deck:
    layers = []
    if coloring == "density":
        data = density_points(points)
        layers.append(
            pdk.Layer(
                "HeatmapLayer",
                data=data[["lon", "lat"]].to_dict("records"),
                get_position="[lon, lat]",
                radius_pixels=25,
            )
        )
    else:
        data = []
        segment = "route_segment" if "route_segment" in points else "segment"
        for _, group in points.groupby(segment, sort=False):
            rows = group.to_dict("records")
            for left, right in zip(rows[:-1], rows[1:], strict=True):
                value = right.get("bpm" if coloring == "hr" else "pace_min_km")
                color = (
                    [128, 128, 128]
                    if pd.isna(value)
                    else [
                        int(max(0, min(255, (value - 50) * 2 if coloring == "hr" else value * 20))),
                        100,
                        200,
                    ]
                )
                data.append(
                    {
                        "path": [[left["lon"], left["lat"]], [right["lon"], right["lat"]]],
                        "color": color,
                    }
                )
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=data,
                get_path="path",
                get_color="color",
                width_min_pixels=3,
                wrap_longitude=True,
                pickable=False,
            )
        )
    view = pdk.ViewState(
        latitude=float(points.lat.mean()) if not points.empty else 0,
        longitude=float(points.lon.mean()) if not points.empty else 0,
        zoom=12,
    )
    kwargs = (
        {"map_provider": None}
        if offline
        else {"map_provider": "mapbox", "map_style": "/app/static/osm.json"}
    )
    return pdk.Deck(layers=layers, initial_view_state=view, tooltip=False, **kwargs)
