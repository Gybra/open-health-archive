from datetime import UTC, datetime

from healthviz.archive.values import number, offset_text, utc_iso
from healthviz.xiaomi.devices import device_for, provenance
from healthviz.xiaomi.mapping import append_row, numeric

KEYS = {
    "heart_rate": "heart_rate",
    "steps": "steps",
    "calories": "calories",
    "resting_heart_rate": "resting_heart_rate",
    "spo2": "spo2",
    "single_spo2": "spo2",
    "weight": "weight",
}
DROPPED = {"sleep", "intensity", "valid_stand", "min_heart_rate", "max_heart_rate"}


def sample_rows(source, value, device, offsets):
    key, time = source["Key"], int(source["Time"])
    fields = provenance(device, f"{device.device_id}:{key}:{time}")
    offset = offset_text(offsets.minutes_at(time))
    if key == "resting_heart_rate":
        # The vendor encodes the local calendar date as UTC midnight, not a local instant.
        date = datetime.fromtimestamp(numeric(value, "date_time", True), UTC).date().isoformat()
        return [
            (
                "resting_heart_rate",
                dict(
                    date_local=date,
                    bpm=number(numeric(value, "bpm", True)),
                    computed_by="vendor",
                    **fields,
                ),
            )
        ]
    if key in ("heart_rate", "spo2", "single_spo2", "weight"):
        field, target = {
            "heart_rate": ("bpm", "bpm"),
            "spo2": ("spo2", "percent"),
            "single_spo2": ("spo2", "percent"),
            "weight": ("weight", "kg"),
        }[key]
        return [
            (
                KEYS[key],
                dict(
                    time_utc=utc_iso(time),
                    utc_offset=offset,
                    **{target: number(numeric(value, field, True))},
                    **fields,
                ),
            )
        ]
    # Xiaomi minute timestamps are assumed to mark bucket starts; end is inferred +60s.
    interval = dict(
        start_utc=utc_iso(time), end_utc=utc_iso(time + 60), utc_offset=offset, **fields
    )
    if key == "calories":
        return [
            (
                "calories",
                dict(**interval, kind="active", kcal=number(numeric(value, "calories", True))),
            )
        ]
    result = [("steps", dict(**interval, count=number(numeric(value, "steps", True))))]
    distance = numeric(value, "distance")
    if distance is not None and distance > 0:
        result.append(("distance", dict(**interval, distance_m=number(distance))))
    # steps.calories is already included in the calories stream; never sum both.
    return result


def map_samples(export, devices, offsets):
    tables = {name: [] for name in {*KEYS.values(), "distance"}}
    for line, source in export.rows("fitness_data"):
        key = source["Key"]
        if key in DROPPED:
            continue
        if key not in KEYS:
            export.warn_once("fitness_data", "unknown metric skipped")
            continue
        value = export.json_value("fitness_data", line, source["Value"])
        if value is None:
            continue
        try:
            device = device_for(export, devices, source, "fitness_data")
            for table, row in sample_rows(source, value, device, offsets):
                append_row(export, "fitness_data", line, table, row, tables[table])
        except (ValueError, TypeError, OverflowError, OSError):
            export.warn("fitness_data", line, "invalid measurement record")
    return tables
