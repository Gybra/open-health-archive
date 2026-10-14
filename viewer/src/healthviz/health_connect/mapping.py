"""Health Connect export rows → archive schema v1 rows, devices and GPX tracks."""

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from healthviz.archive.devices import Device
from healthviz.archive.schema import TABLES, Row
from healthviz.archive.validate import validate_row
from healthviz.archive.values import local_date, number, offset_text, utc_iso
from healthviz.health_connect.export import REQUIRED, ExportError, HealthConnectExport
from healthviz.health_connect.gpx import route_gpx
from healthviz.health_connect.names import archive_stage, exercise_name, stage_name, workout_type

INGEST = "health_connect"
# Apps that only relay their own wearables' data, so an unknown device type is the wearable.
WEARABLE_APPS = frozenset({"com.xiaomi.wearable"})
WATCH_TYPES = frozenset({1, 6})
PHONE_TYPE = 2
# Converted-value bounds; outside them a value is implausible, not merely unusual.
BOUNDS = {
    "heart_rate": ("bpm", 20, 250),
    "resting_heart_rate": ("bpm", 20, 150),
    "spo2": ("percent", 50, 100),
    "weight": ("kg", 20, 300),
    "steps": ("count", 0, 100_000),
    "distance": ("distance_m", 0, 500_000),
    ("calories", "active"): ("kcal", 0, 10_000),
    ("calories", "total"): ("kcal", 0, 20_000),
}
# A record whose values cannot be converted is skipped and counted, never fatal.
CONVERSION_ERRORS = (ValueError, TypeError, OverflowError, OSError)
# A few typos are dropped; a table this wrong means the stored unit changed.
STOP_SHARE, STOP_MINIMUM = 0.01, 3


@dataclass
class Mapped:
    tables: dict[str, list[Row]] = field(default_factory=dict)
    devices: dict[str, Device] = field(default_factory=dict)
    tracks: dict[str, bytes] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)


class Mapper:
    def __init__(self, export: HealthConnectExport, zone: ZoneInfo):
        self.export, self.zone, self.result = export, zone, Mapped()

    def skip(self, table: str) -> None:
        self.result.skipped[table] = self.result.skipped.get(table, 0) + 1

    @contextmanager
    def record(self, table: str):
        try:
            yield
        except CONVERSION_ERRORS:
            self.skip(table)

    def add(self, table: str, **values) -> None:
        row = {column: str(values.get(column, "")) for column in TABLES[table].columns}
        self.result.tables.setdefault(table, []).append(row)

    def offset(self, millis: int, seconds: int | None) -> str:
        if seconds is None:
            instant = datetime.fromtimestamp(millis / 1000, UTC)
            seconds = int(self.zone.utcoffset(instant).total_seconds())
        return offset_text(seconds // 60)

    def provenance(self, app_id: int, device_row: int | None, record_id: str) -> dict:
        package = self.export.apps.get(app_id, "")
        device = self.export.devices.get(device_row) if device_row is not None else None
        manufacturer, model, kind_code = device or ("", "", None)
        key = f"{package}|{manufacturer}|{model}|{'' if kind_code is None else kind_code}"
        device_id = "hc-" + hashlib.sha256(key.encode()).hexdigest()[:16]
        self.result.devices[device_id] = Device(
            device_id, manufacturer, model, device_kind(package, device is not None, kind_code)
        )
        return dict(device_id=device_id, ingest=INGEST, source_app=package, record_id=record_id)

    def interval_rows(self, table: str, target: str):
        """Records of an export table, already converted; unconvertible ones count for target."""
        for row_id, uid, app_id, device, start, start_offset, end, _, *values in self.export.rows(
            table, REQUIRED[table]
        ):
            with self.record(target):
                fields = {
                    "start_utc": utc_iso(start // 1000),
                    "end_utc": utc_iso(-(-end // 1000)),
                    "utc_offset": self.offset(start, start_offset),
                }
                yield row_id, values, {**fields, **self.provenance(app_id, device, uid.hex())}

    def instant_rows(self, table: str, target: str):
        for _, uid, app_id, device, time, offset, *values in self.export.rows(
            table, REQUIRED[table]
        ):
            with self.record(target):
                fields = {
                    "time_utc": utc_iso(time // 1000),
                    "utc_offset": self.offset(time, offset),
                }
                yield values, {**fields, **self.provenance(app_id, device, uid.hex())}


def device_kind(package: str, has_device: bool, code: int | None) -> str:
    if not has_device:
        return "app"
    if code in WATCH_TYPES:
        return "watch"
    if code == PHONE_TYPE:
        return "phone"
    return "watch" if package in WEARABLE_APPS else "other"


def map_intervals(m: Mapper) -> None:
    for table, kind in (
        ("active_calories_burned_record_table", "active"),
        ("total_calories_burned_record_table", "total"),
    ):
        for _, (energy,), fields in m.interval_rows(table, "calories"):
            with m.record("calories"):
                m.add("calories", kind=kind, kcal=number(energy / 1000), **fields)
    for _, (count,), fields in m.interval_rows("steps_record_table", "steps"):
        m.add("steps", count=count, **fields)
    for _, (distance,), fields in m.interval_rows("distance_record_table", "distance"):
        with m.record("distance"):
            m.add("distance", distance_m=number(float(distance)), **fields)


def map_instants(m: Mapper) -> None:
    for (percent,), fields in m.instant_rows("oxygen_saturation_record_table", "spo2"):
        with m.record("spo2"):
            m.add("spo2", percent=number(float(percent)), **fields)
    for (grams,), fields in m.instant_rows("weight_record_table", "weight"):
        with m.record("weight"):
            m.add("weight", kg=number(grams / 1000), **fields)
    for (bpm,), fields in m.instant_rows("resting_heart_rate_record_table", "resting_heart_rate"):
        with m.record("resting_heart_rate"):
            date = local_date(fields.pop("time_utc"), fields.pop("utc_offset"))
            m.add("resting_heart_rate", date_local=date, bpm=bpm, computed_by="vendor", **fields)


def map_heart_rate(m: Mapper) -> None:
    samples = m.export.children(
        "heart_rate_record_series_table", "parent_key", ("epoch_millis", "beats_per_minute")
    )
    for row_id, _, fields in m.interval_rows("heart_rate_record_table", "heart_rate"):
        record = fields["record_id"]
        for millis, bpm in samples.get(row_id, []):
            with m.record("heart_rate"):
                m.add(
                    "heart_rate",
                    time_utc=utc_iso(millis // 1000),
                    bpm=bpm,
                    **{**fields, "record_id": f"{record}@{millis}"},
                )


def map_sleep(m: Mapper) -> None:
    stages = m.export.children(
        "sleep_stages_table", "parent_key", ("stage_start_time", "stage_end_time", "stage_type")
    )
    for row_id, _, fields in m.interval_rows("sleep_session_record_table", "sleep_sessions"):
        session = fields["record_id"]
        own = stages.get(row_id, [])
        has_stages = "true" if own else "false"
        m.add(
            "sleep_sessions",
            session_id=session,
            has_stages=has_stages,
            computed_by="vendor",
            **fields,
        )
        provenance = {k: fields[k] for k in ("device_id", "ingest", "source_app")}
        for start, end, code in own:
            with m.record("sleep_stages"):
                m.add(
                    "sleep_stages",
                    session_id=session,
                    start_utc=utc_iso(start // 1000),
                    end_utc=utc_iso(-(-end // 1000)),
                    stage=archive_stage(code),
                    source_type=stage_name(code),
                    record_id=f"{session}@{start}",
                    **provenance,
                )


def map_workouts(m: Mapper) -> None:
    routes = m.export.children(
        "exercise_route_table",
        "parent_key",
        ("timestamp_millis", "latitude", "longitude", "altitude"),
    )
    for row_id, (code,), fields in m.interval_rows("exercise_session_record_table", "workouts"):
        with m.record("workouts"):
            workout = fields["record_id"]
            track = f"tracks/{workout}.gpx" if routes.get(row_id) else ""
            if track:
                m.result.tracks[track] = route_gpx(routes[row_id])
            m.add(
                "workouts",
                workout_id=workout,
                type=workout_type(code),
                source_type=exercise_name(code),
                track_file=track,
                **fields,
            )


def bound_for(table: str, row: Row):
    return BOUNDS.get((table, row["kind"])) if table == "calories" else BOUNDS.get(table)


def drop_unusable(result: Mapped) -> None:
    """Rows the archive would reject are skipped; many implausible values stop the import."""
    for table, rows in result.tables.items():
        valid = [row for row in rows if not validate_row(TABLES[table], row)]
        kept = []
        for row in valid:
            bound = bound_for(table, row)
            if bound is None or bound[1] <= float(row[bound[0]]) <= bound[2]:
                kept.append(row)
        implausible = len(valid) - len(kept)
        if implausible >= STOP_MINIMUM and implausible > STOP_SHARE * len(rows):
            raise ExportError(f"implausible {table} values; the export format may have changed")
        if len(kept) < len(rows):
            result.skipped[table] = result.skipped.get(table, 0) + len(rows) - len(kept)
            result.tables[table] = kept


def map_export(export: HealthConnectExport, zone: ZoneInfo) -> Mapped:
    mapper = Mapper(export, zone)
    for step in (map_intervals, map_instants, map_heart_rate, map_sleep, map_workouts):
        step(mapper)
    drop_unusable(mapper.result)
    linked = {row["track_file"] for row in mapper.result.tables.get("workouts", [])}
    mapper.result.tracks = {k: v for k, v in mapper.result.tracks.items() if k in linked}
    return mapper.result
