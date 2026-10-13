from pathlib import Path

from healthviz.archive.schema import TABLES
from healthviz.archive.writer import write_archive

TIME = "2026-01-01T00:00:00Z"
END = "2026-01-01T01:00:00Z"
GPX = (
    b'<gpx version="1.1" creator="synthetic"><trk><trkseg>'
    b'<trkpt lat="0.001" lon="0.001"><time>2026-01-01T00:00:00Z</time></trkpt>'
    b'<trkpt lat="0.002" lon="0.002"><time>2026-01-01T00:01:00Z</time></trkpt>'
    b'<trkpt lat="0.003" lon="0.003"><time>2026-01-01T00:02:00Z</time></trkpt>'
    b"</trkseg></trk></gpx>"
)


def fixture_row(name, **fields):
    row = dict.fromkeys(TABLES[name].columns, "")
    row.update(device_id="fixture-watch", ingest="synthetic", record_id=name)
    row.update(fields)
    return row


FIXTURE_DEVICES = [
    dict(
        device_id=f"fixture-{kind}",
        vendor="Fictional",
        model=f"Test {kind}",
        kind=kind,
        first_seen_utc=TIME,
        last_seen_utc=END,
    )
    for kind in ("watch", "phone")
]
INTERVAL = dict(start_utc=TIME, end_utc=END, utc_offset="+01:00")
FIXTURE_TABLES = {
    "heart_rate": [fixture_row("heart_rate", time_utc=TIME, utc_offset="+01:00", bpm="60")],
    "steps": [fixture_row("steps", **INTERVAL, count="80")],
    "distance": [fixture_row("distance", **INTERVAL, distance_m="55")],
    "calories": [fixture_row("calories", **INTERVAL, kind="active", kcal="3")],
    "sleep_sessions": [
        fixture_row(
            "sleep_sessions",
            **INTERVAL,
            session_id="night",
            has_stages="true",
            is_complete="true",
            computed_by="device",
        ),
        fixture_row(
            "sleep_sessions",
            start_utc="2026-01-02T00:00:00Z",
            end_utc="2026-01-02T01:00:00Z",
            utc_offset="+01:00",
            session_id="old-night",
            record_id="old-night",
            has_stages="false",
            deep_min="20",
            light_min="40",
            awake_min="0",
            computed_by="vendor",
        ),
    ],
    "sleep_stages": [
        fixture_row("sleep_stages", session_id="night", start_utc=TIME, end_utc=END, stage="light")
    ],
    "workouts": [
        fixture_row(
            "workouts",
            **INTERVAL,
            workout_id="walk",
            type="walking",
            distance_m="4200",
            track_file="tracks/walk.gpx",
        ),
        fixture_row(
            "workouts", **INTERVAL, workout_id="gym", type="strength_training", record_id="gym"
        ),
    ],
    "resting_heart_rate": [
        fixture_row("resting_heart_rate", date_local="2026-01-01", bpm="55", computed_by="vendor")
    ],
    "spo2": [fixture_row("spo2", time_utc=TIME, utc_offset="+01:00", percent="98")],
    "weight": [fixture_row("weight", time_utc=TIME, utc_offset="+01:00", kg="65.0")],
    "daily_vendor_summaries": [
        fixture_row(
            "daily_vendor_summaries",
            date_local="2025-12-31",
            metric="steps",
            value="4000",
            unit="count",
            computed_by="vendor",
        )
    ],
}
FIXTURE_TRACKS = {"tracks/walk.gpx": GPX}

if __name__ == "__main__":
    write_archive(
        Path("/workspace/schema/fixtures/archive"),
        FIXTURE_TABLES,
        FIXTURE_DEVICES,
        FIXTURE_TRACKS,
        "healthviz fixtures",
    )
