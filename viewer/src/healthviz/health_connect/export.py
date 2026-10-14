"""Read-only access to Health Connect's export zip: one SQLite copy of its database."""

import re
import sqlite3
import zipfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

MEMBER = "health_connect_export.db"
MAX_DB_BYTES = 1 << 30
TESTED_VERSIONS = frozenset({26})

RECORD = ("row_id", "uuid", "app_info_id", "device_info_id")
INTERVAL = (*RECORD, "start_time", "start_zone_offset", "end_time", "end_zone_offset")
INSTANT = (*RECORD, "time", "zone_offset")

# Every column the importer reads; a missing one means Google changed the format.
REQUIRED: dict[str, tuple[str, ...]] = {
    "application_info_table": ("row_id", "package_name"),
    "device_info_table": ("row_id", "manufacturer", "model", "device_type"),
    "steps_record_table": (*INTERVAL, "count"),
    "distance_record_table": (*INTERVAL, "distance"),
    "active_calories_burned_record_table": (*INTERVAL, "energy"),
    "total_calories_burned_record_table": (*INTERVAL, "energy"),
    "heart_rate_record_table": INTERVAL,
    "heart_rate_record_series_table": ("parent_key", "beats_per_minute", "epoch_millis"),
    "sleep_session_record_table": INTERVAL,
    "sleep_stages_table": ("parent_key", "stage_start_time", "stage_end_time", "stage_type"),
    "exercise_session_record_table": (*INTERVAL, "exercise_type"),
    "exercise_route_table": ("parent_key", "timestamp_millis", "latitude", "longitude", "altitude"),
    "oxygen_saturation_record_table": (*INSTANT, "percentage"),
    "resting_heart_rate_record_table": (*INSTANT, "beats_per_minute"),
    "weight_record_table": (*INSTANT, "weight"),
}
MAPPED_TABLES = frozenset(name for name in REQUIRED if name.endswith("_record_table"))
RECORD_TABLE = re.compile(r"[a-z_]+_record_table")


class ExportError(Exception):
    """Fixed English messages only: export contents never reach an error text."""


def is_export(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return MEMBER in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def newest_export(folder: Path) -> Path | None:
    candidates = [
        p
        for p in folder.iterdir()
        if p.suffix.lower() == ".zip" and p.is_file() and not p.is_symlink() and is_export(p)
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def extract(zip_path: Path, workdir: Path) -> Path:
    target = workdir / MEMBER
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo(MEMBER)
        if info.file_size > MAX_DB_BYTES:
            raise ExportError("Health Connect export is too large")
        with archive.open(info) as source, target.open("xb") as out:
            target.chmod(0o600)
            written = 0
            while chunk := source.read(1 << 20):
                written += len(chunk)
                if written > MAX_DB_BYTES:
                    raise ExportError("Health Connect export is too large")
                out.write(chunk)
    return target


class HealthConnectExport:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.format_version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.format_tested = self.format_version in TESTED_VERSIONS
        for table, columns in REQUIRED.items():
            present = {row[1] for row in connection.execute(f"PRAGMA table_xinfo({table})")}
            if not set(columns) <= present:
                raise ExportError("unsupported Health Connect export format")
        self.apps = dict(self.rows("application_info_table", ("row_id", "package_name")))
        self.devices = {
            row_id: (manufacturer or "", model or "", device_type or 0)
            for row_id, manufacturer, model, device_type in self.rows(
                "device_info_table", REQUIRED["device_info_table"]
            )
        }

    def rows(self, table: str, columns: tuple[str, ...]) -> Iterator[tuple]:
        if not set(columns) <= set(REQUIRED[table]):
            raise ValueError("column not checked by the format test")
        names = ", ".join(columns)
        return self.connection.execute(f"SELECT {names} FROM {table} ORDER BY {columns[0]}")

    def children(
        self, table: str, parent_column: str, columns: tuple[str, ...]
    ) -> dict[int, list[tuple]]:
        result: dict[int, list[tuple]] = {}
        for parent, *values in self.rows(table, (parent_column, *columns)):
            result.setdefault(parent, []).append(tuple(values))
        for values in result.values():
            values.sort()
        return result

    def not_imported(self) -> dict[str, int]:
        names = [
            name
            for (name,) in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            if RECORD_TABLE.fullmatch(name) and name not in MAPPED_TABLES
        ]
        counts = {
            name.removesuffix("_record_table"): self.connection.execute(
                f"SELECT count(*) FROM {name}"
            ).fetchone()[0]
            for name in names
        }
        return {name: count for name, count in sorted(counts.items()) if count}


@contextmanager
def open_export(zip_path: Path, workdir: Path) -> Iterator[HealthConnectExport]:
    try:
        database = extract(zip_path, workdir)
        uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA trusted_schema = OFF")
            yield HealthConnectExport(connection)
    except ExportError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile, sqlite3.Error):
        raise ExportError("cannot read Health Connect export") from None
