import xml.etree.ElementTree as ET
from pathlib import Path

MAX_TRACK_BYTES = 32 * 1024 * 1024


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
