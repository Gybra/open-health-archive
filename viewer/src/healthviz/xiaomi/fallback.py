from datetime import UTC, datetime

from healthviz.archive.values import local_date, positive
from healthviz.xiaomi.devices import device_for, provenance
from healthviz.xiaomi.mapping import append_row, numeric

METRICS = {
    "steps": [("steps", "steps", "count"), ("distance", "distance", "m")],
    "calories": [("active_kcal", "calories", "kcal")],
    "sleep": [("sleep_duration", "total_duration", "min")],
}


def covered_days(tables):
    covered = {}
    for source, table, timecol in (
        ("steps", "steps", "start_utc"),
        ("calories", "calories", "start_utc"),
        ("sleep", "sleep_sessions", "end_utc"),
    ):
        covered[source] = {local_date(r[timecol], r["utc_offset"]) for r in tables.get(table, [])}
    return covered


def map_vendor_daily(export, devices, tables):
    covered, output = covered_days(tables), []
    # Vendor summaries fill days without observations; never add them to raw samples.
    for line, source in export.rows("aggregated_fitness_data"):
        key = source["Key"]
        if source["Tag"] != "daily_report" or key not in METRICS:
            continue
        try:
            day = datetime.fromtimestamp(int(source["Time"]), UTC).date().isoformat()
            if day in covered[key]:
                continue
            value = export.json_value("aggregated_fitness_data", line, source["Value"])
            if value is None:
                continue
            device = device_for(export, devices, source, "aggregated_fitness_data")
            for metric, field, unit in METRICS[key]:
                amount = positive(numeric(value, field))
                if not amount:
                    continue
                row = dict(
                    date_local=day,
                    metric=metric,
                    value=amount,
                    unit=unit,
                    computed_by="vendor",
                    **provenance(device, f"{device.device_id}:{metric}:{day}"),
                )
                append_row(
                    export, "aggregated_fitness_data", line, "daily_vendor_summaries", row, output
                )
        except (ValueError, TypeError, OverflowError, OSError):
            export.warn("aggregated_fitness_data", line, "invalid daily summary")
    return output
