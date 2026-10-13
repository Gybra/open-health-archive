def hr(**changes):
    return {
        "time_utc": "2026-10-12T06:30:00Z",
        "utc_offset": "+02:00",
        "bpm": "60",
        "device_id": "fixture-watch",
        "ingest": "xiaomi_export",
        "source_app": "",
        "record_id": "a",
        **changes,
    }


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
