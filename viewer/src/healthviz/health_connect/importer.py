"""Apply the newest Health Connect export to the archive: upserts plus window-bounded deletions."""

import hashlib
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from healthviz import __version__
from healthviz.archive.devices import device_rows
from healthviz.archive.schema import TABLES, Row
from healthviz.archive.writer import SchemaMismatch, existing_rows, recover_archive, write_archive
from healthviz.health_connect.export import ExportError, newest_export, open_export
from healthviz.health_connect.mapping import INGEST, Mapped, map_export
from healthviz.health_connect.status import ImportStatus, load_status, save_status

WRITE_FAILED = "cannot read the export or write the archive"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def own_rows(archive: Path, table: str) -> list[Row]:
    columns = TABLES[table].columns
    return [
        row
        for path in sorted((archive / table).glob("*.csv"))
        for row in existing_rows(archive, path.relative_to(archive).as_posix(), columns)
        if row["ingest"] == INGEST
    ]


def record_type(row: Row) -> tuple[str, str]:
    """Health Connect type and app: active and total calories are separate types."""
    return row["source_app"], row.get("kind", "")


def windows(rows: list[Row], column: str) -> dict[tuple[str, str], tuple[str, str]]:
    result = {}
    for row in rows:
        key, value = record_type(row), row[column]
        low, high = result.get(key, (value, value))
        result[key] = (min(low, value), max(high, value))
    return result


def deletions(archive: Path, mapped: Mapped) -> tuple[dict[str, set], set[str]]:
    """Own rows missing from the export inside the period it covers for their type and app."""
    delete_keys: dict[str, set] = {}
    tracks: set[str] = set()
    for table in sorted(set(mapped.tables) - {"sleep_stages"}):
        incoming = mapped.tables[table]
        column = TABLES[table].time_column
        covered, kept = windows(incoming, column), {row["record_id"] for row in incoming}
        for row in own_rows(archive, table):
            low, high = covered.get(record_type(row), ("~", ""))
            if row["record_id"] not in kept and low <= row[column] <= high:
                delete_keys.setdefault(table, set()).add((INGEST, row["record_id"]))
                if row.get("track_file"):
                    tracks.add(row["track_file"])
    sessions = {key[1] for key in delete_keys.get("sleep_sessions", ())}
    if sessions:
        delete_keys["sleep_stages"] = {
            (INGEST, stage["record_id"])
            for stage in own_rows(archive, "sleep_stages")
            if stage["session_id"] in sessions
        }
    return delete_keys, tracks


def apply(archive: Path, mapped: Mapped, journal: Path) -> None:
    delete_keys, delete_tracks = deletions(archive, mapped)
    sessions = mapped.tables.get("sleep_sessions", ())
    write_archive(
        archive,
        mapped.tables,
        device_rows(mapped.devices, mapped.tables),
        mapped.tracks,
        generator=f"healthviz {__version__}",
        delete_keys=delete_keys,
        replace_sessions={(INGEST, r["session_id"]) for r in sessions},
        delete_tracks=delete_tracks,
        journal=journal,
    )


def run(
    source: Path, archive: Path, zone: ZoneInfo, journal: Path, status: ImportStatus
) -> ImportStatus:
    recover_archive(archive, journal)
    zip_path = newest_export(source) if source.is_dir() else source
    if zip_path is None:
        raise ExportError("no Health Connect export in the chosen folder")
    status.zip_name, status.zip_sha256 = zip_path.name, digest(zip_path)
    last, manifest = status.last_success or {}, archive / "manifest.json"
    same_archive = last.get("manifest_sha256") == digest(manifest)
    if last.get("zip_sha256") == status.zip_sha256 and same_archive:
        status.already_imported = True
        return status
    with tempfile.TemporaryDirectory() as work, open_export(zip_path, Path(work)) as export:
        mapped = map_export(export, zone)
        status.format_version, status.format_tested = export.format_version, export.format_tested
        status.not_imported = export.not_imported()
    apply(archive, mapped, journal)
    status.counts = {table: len(rows) for table, rows in sorted(mapped.tables.items())}
    status.skipped = dict(sorted(mapped.skipped.items()))
    status.imported_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    status.last_success = {
        "zip_name": status.zip_name,
        "zip_sha256": status.zip_sha256,
        "imported_at": status.imported_at,
        "manifest_sha256": digest(manifest),
    }
    return status


def recover_now(archive: Path, journal: Path) -> None:
    """Undo a half-applied write at once; if that fails too, the next run retries it."""
    try:
        recover_archive(archive, journal)
    except OSError:
        pass


def import_health_connect(
    source: Path,
    archive: Path,
    *,
    zone: ZoneInfo,
    status: Path,
    journal: Path,
    label: str = "",
) -> ImportStatus:
    previous = load_status(status)
    current = ImportStatus(folder=label, last_success=previous.last_success if previous else None)
    try:
        result = run(source, archive, zone, journal, current)
        if result.already_imported and previous is not None:
            result = replace(previous, already_imported=True, error=None, folder=label)
    except (ExportError, SchemaMismatch) as error:
        result = replace(current, error=str(error))
    except OSError:
        result = replace(current, error=WRITE_FAILED)
        recover_now(archive, journal)
    except Exception:  # the status must always reflect the run, never the error text
        result = replace(current, error="unexpected error while importing")
        recover_now(archive, journal)
    try:
        save_status(status, result)
    except OSError:
        result = replace(result, error=result.error or "cannot save the import status")
    return result
