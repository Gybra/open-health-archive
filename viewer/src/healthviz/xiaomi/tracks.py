import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from healthviz.archive.validate import safe_track_path
from healthviz.archive.values import parse_utc

type Fetch = Callable[[str], bytes]
MAX_TRACK_BYTES = 32 * 1024 * 1024


def checked_url(url):
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


def validate_gpx(data: bytes) -> None:
    if len(data) > MAX_TRACK_BYTES or b"<!DOCTYPE" in data.upper():
        raise ValueError("invalid GPX")
    root = ET.fromstring(data)
    if root.tag.split("}")[-1] != "gpx":
        raise ValueError("not GPX")


def track_bytes(path: Path) -> bytes:
    if path.is_symlink() or path.stat().st_size > MAX_TRACK_BYTES:
        raise ValueError("unsafe track")
    return path.read_bytes()


def collect_tracks(export, workouts, archive_dir, tracks_dir, fetch: Fetch = download):
    by_time = {parse_utc(w["start_utc"]): w for w in workouts}
    tracks = {}
    # GPX contains signed, expiring URLs; prefer the user's local backup.
    for line, source in export.rows("sport_track_data"):
        try:
            time = int(source["Time"])
            workout = by_time.get(time)
            if workout is None:
                export.warn("sport_track_data", line, "no workout starts at this track's time")
                continue
            rel = f"tracks/{workout['workout_id']}.gpx"
            if not safe_track_path(rel):
                raise ValueError("unsafe workout ID")
            saved = archive_dir / rel
            if saved.exists():
                validate_gpx(track_bytes(saved))
            else:
                local = tracks_dir / f"{time}.gpx" if tracks_dir else None
                data = track_bytes(local) if local and local.exists() else fetch(source["GPX"])
                validate_gpx(data)
                tracks[rel] = data
            workout["track_file"] = rel
        except (OSError, ValueError, ET.ParseError) as error:
            # Exception messages may contain signed URLs; retain only the class.
            export.warn("sport_track_data", line, f"track unavailable ({type(error).__name__})")
    return tracks
