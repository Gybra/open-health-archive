import http.client
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from urllib.parse import urlsplit

from healthviz.archive.gpx import MAX_TRACK_BYTES, track_bytes, validate_gpx
from healthviz.archive.validate import safe_track_path
from healthviz.archive.values import parse_utc
from healthviz.xiaomi.devices import load_devices

type Fetch = Callable[[str], bytes]


def checked_url(url):
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("invalid URL")
    p = urlsplit(url)
    host = p.hostname or ""
    if (
        p.scheme != "https"
        or not (host == "fds.api.xiaomi.com" or host.endswith(".fds.api.xiaomi.com"))
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise ValueError("unsupported track URL")


class XiaomiRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str) -> bytes:
    checked_url(url)
    opener = urllib.request.build_opener(XiaomiRedirect())
    with opener.open(url, timeout=60) as response:
        data = response.read(MAX_TRACK_BYTES + 1)
    if len(data) > MAX_TRACK_BYTES:
        raise ValueError("track too large")
    return data


def reuse_existing_tracks(workouts, archive_dir, export):
    for workout in workouts:
        rel = f"tracks/{workout['workout_id']}.gpx"
        saved = archive_dir / rel
        if not safe_track_path(rel):
            continue
        if saved.exists():
            try:
                validate_gpx(track_bytes(saved))
                workout["track_file"] = rel
            except (OSError, ValueError, ET.ParseError):
                export.warn_once("sport_track_data", "existing track is invalid")


def track_workout(export, source, candidates, devices, line):
    device = devices.get(source.get("Did"))
    if device:
        candidates = [w for w in candidates if w["device_id"] == device.device_id]
    if len(candidates) != 1:
        reason = (
            "ambiguous workout for track"
            if candidates
            else "no workout starts at this track's time"
        )
        export.warn("sport_track_data", line, reason)
        return None
    return candidates[0]


def collect_tracks(export, workouts, archive_dir, tracks_dir, fetch: Fetch = download):
    reuse_existing_tracks(workouts, archive_dir, export)
    by_time = defaultdict(list)
    for workout in workouts:
        by_time[parse_utc(workout["start_utc"])].append(workout)
    devices, tracks = load_devices(export), {}
    # GPX contains signed, expiring URLs; prefer the user's local backup.
    for line, source in export.rows("sport_track_data"):
        try:
            time = int(source["Time"])
            workout = track_workout(export, source, by_time[time], devices, line)
            if workout is None or workout["track_file"]:
                continue
            rel = f"tracks/{workout['workout_id']}.gpx"
            if not safe_track_path(rel):
                raise ValueError("unsafe workout ID")
            local = tracks_dir / f"{time}.gpx" if tracks_dir else None
            data = track_bytes(local) if local and local.exists() else fetch(source["GPX"])
            validate_gpx(data)
            tracks[rel] = data
            workout["track_file"] = rel
        except (OSError, ValueError, ET.ParseError, http.client.HTTPException) as error:
            # Exception messages may contain signed URLs; retain only the class.
            export.warn("sport_track_data", line, f"track unavailable ({type(error).__name__})")
    return tracks
