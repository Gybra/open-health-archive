from healthviz.archive.values import offset_text
from healthviz.xiaomi.devices import device_for, provenance
from healthviz.xiaomi.mapping import MappingError, append_row, numeric, timestamp, vendor_minutes

# Verified against vendor totals; unobserved state 4 is not assumed to mean REM.
STAGES = {2: "deep", 3: "light", 5: "awake"}


def stage_rows(value, session, provenance_fields):
    stages = []
    for item in value.get("items", []):
        if not isinstance(item, dict):
            raise MappingError("invalid sleep stage")
        start, end = timestamp(item, "start_time"), timestamp(item, "end_time")
        state = numeric(item, "state", required=True)
        stages.append(
            dict(
                session_id=session,
                start_utc=start,
                end_utc=end,
                stage=STAGES.get(state, "unknown"),
                source_type=str(state),
                **{**provenance_fields, "record_id": f"{session}:{start}"},
            )
        )
    return stages


def session_rows(source, value, device):
    session = f"xiaomi-sleep-{source['Time']}"
    fields = provenance(device, session)
    stages = stage_rows(value, session, fields)
    row = dict(
        session_id=session,
        start_utc=timestamp(value, "bedtime"),
        end_utc=timestamp(value, "wake_up_time"),
        utc_offset=offset_text(int(numeric(value, "timezone", required=True) * 15)),
        has_stages="true" if stages else "false",
        computed_by="device" if stages else "vendor",
        **fields,
    )
    if "is_uncomplete" in value:
        row["is_complete"] = "false" if value["is_uncomplete"] else "true"
    if not stages:
        for target, field in (
            ("deep_min", "sleep_deep_duration"),
            ("light_min", "sleep_light_duration"),
            ("awake_min", "sleep_awake_duration"),
        ):
            row[target] = vendor_minutes(value, field)
    return row, stages


def map_sleep(export, devices):
    output = {"sleep_sessions": [], "sleep_stages": []}
    for line, source in export.rows("fitness_data"):
        if source["Key"] != "sleep":
            continue
        value = export.json_value("fitness_data", line, source["Value"])
        if value is None:
            continue
        try:
            row, stages = session_rows(
                source, value, device_for(export, devices, source, "fitness_data")
            )
            if append_row(
                export, "fitness_data", line, "sleep_sessions", row, output["sleep_sessions"]
            ):
                for stage in stages:
                    append_row(
                        export, "fitness_data", line, "sleep_stages", stage, output["sleep_stages"]
                    )
        except (MappingError, ValueError, TypeError, OverflowError):
            export.warn("fitness_data", line, "invalid sleep record")
    return output
