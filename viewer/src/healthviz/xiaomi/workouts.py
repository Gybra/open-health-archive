import hashlib

from healthviz.archive.values import number, offset_text, positive
from healthviz.xiaomi.devices import device_for, provenance
from healthviz.xiaomi.mapping import append_row, numeric, timestamp

TYPES = {
    "outdoor_walking": "walking",
    "cross_fit": "high_intensity_interval_training",
    "free_training": "other_workout",
    "lower_limb_training": "strength_training",
}
POSITIVE_FIELDS = {
    "duration_s": "duration",
    "distance_m": "distance",
    "steps": "steps",
    "active_kcal": "calories",
    "total_kcal": "total_cal",
    "avg_hr": "avg_hrm",
    "max_hr": "max_hrm",
}


def workout_id(key: str, time: int, device_id: str) -> str:
    # Full source key preserves unknown types without putting them in filenames.
    fingerprint = hashlib.sha256(f"{device_id}\0{key}\0{time}".encode()).hexdigest()[:16]
    return f"xiaomi-{fingerprint}"


def workout_row(source, value, device):
    key, time = source["Key"], int(source["Time"])
    identifier = workout_id(key, time, device.device_id)
    row = dict(
        workout_id=identifier,
        type=TYPES.get(key, "other_workout"),
        source_type=key,
        start_utc=timestamp(value, "start_time"),
        end_utc=timestamp(value, "end_time"),
        utc_offset=offset_text(int(numeric(value, "timezone", required=True) * 15)),
        **provenance(device, identifier),
    )
    for target, field in POSITIVE_FIELDS.items():
        row[target] = positive(numeric(value, field))
    for target, field in (("ascent_m", "rise_height"), ("descent_m", "fall_height")):
        row[target] = number(numeric(value, field))
    if row["ascent_m"] or row["descent_m"]:
        row["ascent_computed_by"] = "vendor"
    return row


def map_workouts(export, devices):
    rows = []
    for line, source in export.rows("sport_record"):
        value = export.json_value("sport_record", line, source["Value"])
        if value is None:
            continue
        if source["Key"] not in TYPES:
            export.warn_once("sport_record", "unknown workout type preserved")
        try:
            row = workout_row(source, value, device_for(export, devices, source, "sport_record"))
            append_row(export, "sport_record", line, "workouts", row, rows)
        except (ValueError, TypeError, OverflowError):
            export.warn("sport_record", line, "invalid workout record")
    return rows
