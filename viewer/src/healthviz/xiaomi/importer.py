from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from healthviz import __version__
from healthviz.archive.schema import TABLES
from healthviz.archive.writer import write_archive
from healthviz.xiaomi.devices import load_devices
from healthviz.xiaomi.fallback import map_vendor_daily
from healthviz.xiaomi.offsets import OffsetResolver, anchors_from
from healthviz.xiaomi.samples import map_samples
from healthviz.xiaomi.sleep import map_sleep
from healthviz.xiaomi.source import ExportError, open_export
from healthviz.xiaomi.tracks import Fetch, collect_tracks, download
from healthviz.xiaomi.workouts import map_workouts


@dataclass
class ImportResult:
    counts: dict[str, int]
    warnings: list[str]
    tracks_linked: int
    tracks_missing: int


def device_rows(devices, tables):
    ranges = {}
    by_id = {d.device_id: d for d in devices.values()}
    for name, rows in tables.items():
        column = TABLES[name].time_column
        for row in rows:
            stamp = row[column]
            if column == "date_local":
                stamp += "T00:00:00Z"
            lo, hi = ranges.get(row["device_id"], (stamp, stamp))
            ranges[row["device_id"]] = (min(lo, stamp), max(hi, stamp))
    result = []
    for identifier, (first, last) in sorted(ranges.items()):
        device = by_id.get(identifier)
        if device:
            result.append({**asdict(device), "first_seen_utc": first, "last_seen_utc": last})
        else:
            result.append(
                dict(
                    device_id=identifier,
                    vendor="",
                    model="",
                    kind="other",
                    first_seen_utc=first,
                    last_seen_utc=last,
                )
            )
    return result


def import_xiaomi(
    export_path: Path,
    archive_dir: Path,
    *,
    zone: ZoneInfo,
    tracks_dir: Path | None = None,
    fetch: Fetch = download,
) -> ImportResult:
    export_path, archive_dir = Path(export_path), Path(archive_dir)
    input_root, output_root = export_path.resolve(), archive_dir.resolve()
    if (
        input_root == output_root
        or output_root.is_relative_to(input_root)
        or input_root.is_relative_to(output_root)
    ):
        raise ExportError("input and output must be separate folders")
    export = open_export(export_path)
    devices = load_devices(export)
    tables = map_sleep(export, devices)
    tables["workouts"] = map_workouts(export, devices)
    offsets = OffsetResolver(zone, anchors_from(tables["sleep_sessions"] + tables["workouts"]))
    tables.update(map_samples(export, devices, offsets))
    tracks = collect_tracks(export, tables["workouts"], archive_dir, tracks_dir, fetch)
    tables["daily_vendor_summaries"] = map_vendor_daily(export, devices, tables)
    write_archive(
        archive_dir,
        tables,
        device_rows(devices, tables),
        tracks,
        generator=f"healthviz {__version__}",
        delete_keys={"distance": {(r["ingest"], r["record_id"]) for r in tables["steps"]}},
        replace_sessions={(r["ingest"], r["session_id"]) for r in tables["sleep_sessions"]},
    )
    linked = sum(bool(w["track_file"]) for w in tables["workouts"])
    expected = sum(1 for _ in export.rows("sport_track_data"))
    return ImportResult(
        {name: len(rows) for name, rows in tables.items()},
        export.warnings,
        linked,
        max(expected - linked, 0),
    )
