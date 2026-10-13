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

# Additional contract examples remain fictional, including both same-model watches.
FIXTURE_DEVICES.append({**FIXTURE_DEVICES[0], "device_id": "fixture-watch-2"})
for hour in range(10):
    FIXTURE_TABLES["heart_rate"].append(
        fixture_row(
            "heart_rate",
            record_id=f"complete-{hour}",
            time_utc=f"2026-01-03T{hour:02}:00:00Z",
            utc_offset="+01:00",
            bpm="60",
        )
    )
for key, time, offset, device in (
    ("spring-before", "2026-03-29T00:00:00Z", "+01:00", "fixture-watch"),
    ("spring-after", "2026-03-29T01:00:00Z", "+02:00", "fixture-watch"),
    ("travel", "2026-03-30T10:00:00Z", "+05:30", "fixture-watch"),
    ("fold-first", "2026-10-25T00:00:00Z", "+02:00", "fixture-watch-2"),
    ("fold-second", "2026-10-25T01:00:00Z", "+01:00", "fixture-watch-2"),
):
    FIXTURE_TABLES["heart_rate"].append(
        fixture_row(
            "heart_rate",
            record_id=key,
            time_utc=time,
            utc_offset=offset,
            bpm="60",
            device_id=device,
        )
    )
FIXTURE_TABLES["spo2"].append(
    fixture_row(
        "spo2",
        record_id="month-boundary",
        time_utc="2025-12-31T23:30:00Z",
        utc_offset="+01:00",
        percent="97",
    )
)
for device, count, ingest in (
    ("fixture-watch", "120", "xiaomi_export"),
    ("fixture-phone", "60", "health_connect"),
):
    FIXTURE_TABLES["steps"].append(
        fixture_row(
            "steps",
            record_id=f"overlap-{device}",
            start_utc="2026-01-03T02:00:00Z",
            end_utc="2026-01-03T02:01:00Z",
            utc_offset="+01:00",
            count=count,
            device_id=device,
            ingest=ingest,
        )
    )
FIXTURE_TABLES["calories"].append(
    fixture_row(
        "calories",
        record_id="total-kcal",
        start_utc="2026-01-03T02:00:00Z",
        end_utc="2026-01-03T02:01:00Z",
        utc_offset="+01:00",
        kind="total",
        kcal="8",
    )
)
for sid, start, end, complete, minutes in (
    ("main-complete", "2026-01-02T22:00:00Z", "2026-01-03T06:00:00Z", "true", "480"),
    ("nap", "2026-01-03T12:00:00Z", "2026-01-03T12:45:00Z", "true", "45"),
    ("incomplete", "2026-01-04T00:00:00Z", "2026-01-04T01:30:00Z", "false", "90"),
):
    FIXTURE_TABLES["sleep_sessions"].append(
        fixture_row(
            "sleep_sessions",
            record_id=sid,
            session_id=sid,
            start_utc=start,
            end_utc=end,
            utc_offset="+01:00",
            has_stages="false",
            is_complete=complete,
            light_min=minutes,
            computed_by="vendor",
        )
    )
FIXTURE_TABLES["workouts"].append(
    fixture_row(
        "workouts",
        record_id="elevated-walk",
        workout_id="elevated-walk",
        type="walking",
        start_utc="2026-01-03T02:00:00Z",
        end_utc="2026-01-03T02:30:00Z",
        utc_offset="+01:00",
        duration_s="1800",
        distance_m="2000",
        active_kcal="100",
        ascent_m="10",
        descent_m="5",
        ascent_computed_by="vendor",
        track_file="tracks/elevated-walk.gpx",
    )
)
FIXTURE_TRACKS["tracks/elevated-walk.gpx"] = (
    b'<gpx version="1.1" creator="synthetic"><trk><trkseg>'
    b'<trkpt lat="0.001" lon="0.001"><time>2026-01-03T02:00:00Z</time><ele>-5</ele></trkpt>'
    b'<trkpt lat="0.002" lon="0.002"><time>2026-01-03T02:01:00Z</time><ele>0</ele></trkpt>'
    b'<trkpt lat="0.003" lon="0.003"><ele>5</ele></trkpt></trkseg></trk></gpx>'
)

if __name__ == "__main__":
    write_archive(
        Path("/workspace/schema/fixtures/archive"),
        FIXTURE_TABLES,
        FIXTURE_DEVICES,
        FIXTURE_TRACKS,
        "healthviz fixtures",
    )
