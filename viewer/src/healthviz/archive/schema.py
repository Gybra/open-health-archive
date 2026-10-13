from dataclasses import dataclass, field

type Row = dict[str, str]
SCHEMA_VERSION = 1
PROVENANCE = ("device_id", "ingest", "source_app", "record_id")


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    partition: str
    required: frozenset[str]
    enums: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def time_column(self) -> str | None:
        return next((c for c in ("time_utc", "start_utc", "date_local") if c in self.columns), None)


def table(name, columns, partition, required=None, **enums) -> Table:
    columns = tuple(columns.split())
    fields = columns + (PROVENANCE if name != "devices" else ())
    required = columns if required is None else tuple(required.split())
    if name != "devices":
        required += ("device_id", "ingest", "record_id")
    return Table(
        name,
        fields,
        partition,
        frozenset(required),
        {k: frozenset(v.split()) for k, v in enums.items()},
    )


TABLES = {
    t.name: t
    for t in [
        table(
            "devices",
            "device_id vendor model kind first_seen_utc last_seen_utc",
            "single",
            "device_id kind",
            kind="watch phone manual app other",
        ),
        table("heart_rate", "time_utc utc_offset bpm", "month"),
        table("steps", "start_utc end_utc utc_offset count", "month"),
        table("distance", "start_utc end_utc utc_offset distance_m", "month"),
        table("calories", "start_utc end_utc utc_offset kind kcal", "month", kind="active total"),
        table(
            "sleep_stages",
            "session_id start_utc end_utc stage source_type",
            "month",
            "session_id start_utc end_utc stage",
            stage="awake light deep rem unknown",
        ),
        table(
            "sleep_sessions",
            "session_id start_utc end_utc utc_offset has_stages is_complete deep_min light_min "
            "rem_min awake_min computed_by",
            "year",
            "session_id start_utc end_utc utc_offset has_stages computed_by",
            computed_by="device vendor app",
        ),
        table(
            "workouts",
            "workout_id type source_type start_utc end_utc utc_offset duration_s distance_m steps "
            "active_kcal total_kcal avg_hr max_hr ascent_m descent_m ascent_computed_by track_file",
            "year",
            "workout_id type start_utc end_utc utc_offset",
            ascent_computed_by="device vendor app",
        ),
        table(
            "resting_heart_rate",
            "date_local bpm computed_by",
            "year",
            computed_by="device vendor app",
        ),
        table("spo2", "time_utc utc_offset percent", "year"),
        table("weight", "time_utc utc_offset kg", "year"),
        table(
            "daily_vendor_summaries",
            "date_local metric value unit computed_by",
            "year",
            metric="steps distance active_kcal sleep_duration",
            computed_by="vendor",
        ),
    ]
}

COLUMN_KINDS = {}
for kind, columns in {
    "utc": "time_utc start_utc end_utc first_seen_utc last_seen_utc",
    "offset": "utc_offset",
    "date": "date_local",
    "int": "bpm count deep_min light_min rem_min awake_min duration_s steps avg_hr max_hr",
    "number": "distance_m kcal active_kcal total_kcal ascent_m descent_m percent kg value",
    "bool": "has_stages is_complete",
}.items():
    COLUMN_KINDS.update(dict.fromkeys(columns.split(), kind))


def partition_path(t: Table, row: Row) -> str:
    if t.partition == "single":
        return f"{t.name}.csv"
    stamp = row[t.time_column]
    return f"{t.name}/{stamp[: 7 if t.partition == 'month' else 4]}.csv"


def sort_key(t: Table, row: Row) -> tuple[str, ...]:
    if t.partition == "single":
        return (row["device_id"],)
    return (row[t.time_column], row["device_id"], row["ingest"], row["record_id"])
