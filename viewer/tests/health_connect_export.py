"""Synthetic Health Connect exports built from the real table structure, never real rows."""

import sqlite3
import zipfile
from pathlib import Path

SCHEMA = Path(__file__).parent / "fixtures/health_connect_v26.sql"
MEMBER = "health_connect_export.db"
MI_FITNESS = "com.xiaomi.wearable"
OTHER_APP = "org.example.tracker"
PHONE_APP = "com.android.healthconnect.phone.0123abcd"
HOUR_MS = 3_600_000
JAN = 1_767_258_000_000  # 2026-01-01T09:00:00Z


def uuid(n: int) -> bytes:
    return n.to_bytes(16, "big")


def uuid_hex(n: int) -> str:
    return uuid(n).hex()


def app(row_id, package):
    return dict(row_id=row_id, package_name=package, app_name=package)


def device(row_id, manufacturer, model, device_type, system_id="SYSTEM-DEVICE-ID"):
    return dict(
        row_id=row_id,
        manufacturer=manufacturer,
        model=model,
        device_type=device_type,
        device_id=system_id,
    )


def interval(n, start_ms, end_ms, *, app_id=1, device_id=1, offset_s=3600, **values):
    return dict(
        row_id=n,
        uuid=uuid(n),
        app_info_id=app_id,
        device_info_id=device_id,
        start_time=start_ms,
        start_zone_offset=offset_s,
        end_time=end_ms,
        end_zone_offset=offset_s,
        **values,
    )


def instant(n, time_ms, *, app_id=1, device_id=1, offset_s=3600, **values):
    return dict(
        row_id=n,
        uuid=uuid(n),
        app_info_id=app_id,
        device_info_id=device_id,
        time=time_ms,
        zone_offset=offset_s,
        **values,
    )


MISSING = 5e-324  # Health Connect stores an absent altitude or accuracy as Double.MIN_VALUE


def route_point(parent, millis, latitude, longitude, altitude=MISSING):
    return dict(
        parent_key=parent,
        timestamp_millis=millis,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        horizontal_accuracy=MISSING,
        vertical_accuracy=MISSING,
    )


def every_type():
    return {
        "steps_record_table": [interval(1, JAN, JAN + 600_000, count=812)],
        "distance_record_table": [interval(2, JAN, JAN + 600_000, distance=640.0)],
        "active_calories_burned_record_table": [interval(3, JAN, JAN + 600_000, energy=250000.0)],
        "total_calories_burned_record_table": [interval(4, JAN, JAN + 600_000, energy=1800000.0)],
        "heart_rate_record_table": [interval(5, JAN, JAN + 120_000)],
        "heart_rate_record_series_table": [
            dict(parent_key=5, beats_per_minute=61, epoch_millis=JAN),
            dict(parent_key=5, beats_per_minute=64, epoch_millis=JAN + 60_000),
        ],
        "sleep_session_record_table": [
            interval(6, JAN - 8 * HOUR_MS, JAN - HOUR_MS, title="Night", notes="PRIVATE-NOTE")
        ],
        "sleep_stages_table": [
            dict(
                parent_key=6,
                stage_start_time=JAN - 8 * HOUR_MS,
                stage_end_time=JAN - 4 * HOUR_MS,
                stage_type=5,
            ),
            dict(
                parent_key=6,
                stage_start_time=JAN - 4 * HOUR_MS,
                stage_end_time=JAN - HOUR_MS,
                stage_type=6,
            ),
        ],
        "exercise_session_record_table": [
            interval(7, JAN, JAN + HOUR_MS, exercise_type=79, has_route=1, title="PRIVATE-TITLE")
        ],
        "exercise_route_table": [
            route_point(7, JAN + i * 60_000, 0.001 * i, 0.002 * i, MISSING if i == 1 else 10.0 + i)
            for i in range(3)
        ],
        "oxygen_saturation_record_table": [instant(8, JAN, percentage=97.0)],
        "resting_heart_rate_record_table": [instant(9, JAN, beats_per_minute=52)],
        "weight_record_table": [instant(10, JAN, weight=70500.0)],
    }


def base_rows():
    return {
        "application_info_table": [app(1, MI_FITNESS), app(2, OTHER_APP), app(3, PHONE_APP)],
        "device_info_table": [device(1, "Xiaomi", "Band", 0), device(2, "Phone", "P1", 2)],
    }


def build_export(path: Path, rows: dict[str, list[dict]], *, user_version=26, member=MEMBER):
    """Write rows into a fresh database with the export's structure and zip it at path."""
    database = path.with_suffix(".db")
    database.unlink(missing_ok=True)
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA.read_text())
        connection.execute(f"PRAGMA user_version = {int(user_version)}")
        for table, records in {**base_rows(), **rows}.items():
            for record in records:
                names = ", ".join(record)
                marks = ", ".join("?" for _ in record)
                connection.execute(
                    f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(record.values())
                )
    connection.close()
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(database, member)
    database.unlink()
    return path
