from healthviz.archive.values import utc_iso

# Health Connect stores an absent altitude as Double.MIN_VALUE (verified on a real export).
MISSING_ALTITUDE = 5e-324


def route_gpx(points: list[tuple[int, float, float, float | None]]) -> bytes:
    """GPX 1.1 track from (epoch millis, latitude, longitude, altitude or None) points."""
    lines = ['<gpx version="1.1" creator="healthviz health-connect"><trk><trkseg>']
    for millis, latitude, longitude, altitude in points:
        elevation = "" if altitude in (None, MISSING_ALTITUDE) else f"<ele>{altitude:.1f}</ele>"
        lines.append(
            f'<trkpt lat="{latitude:.7f}" lon="{longitude:.7f}">{elevation}'
            f"<time>{utc_iso(millis // 1000)}</time></trkpt>"
        )
    lines.append("</trkseg></trk></gpx>\n")
    return "".join(lines).encode()
