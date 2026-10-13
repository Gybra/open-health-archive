import csv
import http.client
from zoneinfo import ZoneInfo

import pytest
from archive_rows import hr, snapshot
from fixture_archive import GPX
from test_sessions import sleep_value, workout_value
from xiaomi_export import aggregated_row, fitness_row, load, sport_row, track_row, write_export

from healthviz.archive.validate import validate_archive
from healthviz.archive.writer import SchemaMismatch, write_archive
from healthviz.xiaomi.devices import load_devices
from healthviz.xiaomi.fallback import map_vendor_daily
from healthviz.xiaomi.importer import import_xiaomi
from healthviz.xiaomi.source import open_export
from healthviz.xiaomi.tracks import collect_tracks, download
from healthviz.xiaomi.workouts import map_workouts

ROME = ZoneInfo("Europe/Rome")
TIME = 1767258000
SOURCES = [dict(Sid=sid, Model="midr.watch.k63a", Name="Same watch") for sid in ("900", "902")]


def read_table(root, name):
    rows = []
    for path in (root / name).glob("*.csv"):
        with path.open() as f:
            rows.extend(csv.DictReader(f))
    return rows


@pytest.mark.parametrize(
    "error", [http.client.IncompleteRead(b"SECRET"), http.client.InvalidURL("SECRET")]
)
def test_http_errors_are_redacted_and_nonfatal(tmp_path, error):
    e, devices = load(
        tmp_path,
        sport=[sport_row("outdoor_walking", TIME, workout_value())],
        tracks=[track_row(TIME, "https://example.invalid/SECRET")],
    )

    def fetch(url):
        raise error

    assert collect_tracks(e, map_workouts(e, devices), tmp_path / "archive", None, fetch) == {}
    assert e.warnings and "SECRET" not in str(e.warnings)


def test_control_character_url_rejected_before_http():
    with pytest.raises(ValueError):
        download("https://cnbj1-fds.fds.api.xiaomi.com/a\x01?Signature=SECRET")


def test_device_identity_survives_rename_and_same_model(tmp_path):
    first = load_devices(open_export(write_export(tmp_path / "first", sources=SOURCES)))
    renamed = [{**r, "Name": "Different label"} for r in SOURCES]
    second = load_devices(open_export(write_export(tmp_path / "second", sources=renamed)))
    assert first["900"].device_id != first["902"].device_id
    assert first["900"].device_id == second["900"].device_id


def test_simultaneous_sessions_and_ambiguous_tracks(tmp_path):
    export = write_export(
        tmp_path / "input",
        sources=SOURCES,
        fitness=[
            fitness_row("sleep", 1767250800, sleep_value(), sid=sid) for sid in ("900", "902")
        ],
        sport=[
            sport_row("PRIVATE_A", TIME, workout_value(), sid="900"),
            sport_row("PRIVATE_B", TIME, workout_value(), sid="900"),
        ],
        tracks=[track_row(TIME, "https://example.invalid/secret")],
    )
    out = tmp_path / "out"
    result = import_xiaomi(export, out, zone=ROME, fetch=lambda url: GPX)
    assert len(read_table(out, "sleep_sessions")) == 2
    assert len(read_table(out, "workouts")) == 2
    assert result.tracks_linked == 0 and any("ambiguous" in x for x in result.warnings)
    assert validate_archive(out) == []


def test_track_matches_device_not_arbitrary_time(tmp_path):
    e, devices = load(
        tmp_path,
        sources=SOURCES,
        sport=[
            sport_row("outdoor_walking", TIME, workout_value(), sid=sid) for sid in ("900", "902")
        ],
        tracks=[track_row(TIME, "https://example.invalid/secret")],
    )
    workouts = map_workouts(e, devices)
    collect_tracks(e, workouts, tmp_path / "out", None, fetch=lambda url: GPX)
    assert bool(workouts[0]["track_file"]) and not workouts[1]["track_file"]


def test_record_moves_partition_without_duplicates(tmp_path):
    row = hr(time_utc="2026-09-30T23:59:00Z")
    other = hr(time_utc=row["time_utc"], ingest="health_connect")
    write_archive(tmp_path, {"heart_rate": [row, other]}, [], {}, "test")
    write_archive(tmp_path, {"heart_rate": [hr()]}, [], {}, "test")
    rows = read_table(tmp_path, "heart_rate")
    assert len(rows) == 2 and other in rows and hr() in rows
    assert validate_archive(tmp_path) == []


@pytest.mark.parametrize("damage", ["header", "checksum"])
def test_untouched_corruption_aborts_before_writes(tmp_path, damage):
    row = hr(time_utc="2026-09-30T23:59:00Z")
    write_archive(tmp_path, {"heart_rate": [row]}, [], {}, "test")
    p = tmp_path / "heart_rate/2026-09.csv"
    p.write_text("wrong,header\n" if damage == "header" else p.read_text().replace(",60,", ",61,"))
    before = snapshot(tmp_path)
    with pytest.raises(SchemaMismatch):
        write_archive(tmp_path, {"heart_rate": [hr()]}, [], {}, "test")
    assert snapshot(tmp_path) == before


def test_corrected_sleep_replaces_owned_stages(tmp_path):
    export = tmp_path / "input"
    out = tmp_path / "out"

    def run(items):
        write_export(export, fitness=[fitness_row("sleep", 1767250800, sleep_value(items=items))])
        import_xiaomi(export, out, zone=ROME)

    run([dict(start_time=1767222000, end_time=1767225600, state=3)])
    run([dict(start_time=1767222060, end_time=1767225660, state=3)])
    assert len(read_table(out, "sleep_stages")) == 1
    assert read_table(out, "sleep_stages")[0]["start_utc"] == "2025-12-31T23:01:00Z"
    run([])
    assert read_table(out, "sleep_stages") == []


def test_corrected_steps_can_retract_derived_distance(tmp_path):
    export, out = tmp_path / "input", tmp_path / "out"
    for distance in (55, 0):
        write_export(
            export, fitness=[fitness_row("steps", TIME, {"steps": 80, "distance": distance})]
        )
        import_xiaomi(export, out, zone=ROME)
    assert read_table(out, "distance") == []
    assert len(read_table(out, "steps")) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_reimport_without_track_metadata_keeps_existing_link(tmp_path, missing):
    export, out = tmp_path / "input", tmp_path / "out"
    sport = [sport_row("outdoor_walking", TIME, workout_value())]
    write_export(export, sport=sport, tracks=[track_row(TIME, "https://example.invalid/secret")])
    import_xiaomi(export, out, zone=ROME, fetch=lambda url: GPX)
    before = read_table(out, "workouts")[0]["track_file"]
    write_export(export, sport=sport, tracks=[])
    if missing:
        next(export.glob("*_hlth_center_sport_track_data.csv")).unlink()
    import_xiaomi(export, out, zone=ROME)
    assert read_table(out, "workouts")[0]["track_file"] == before


def test_fallback_coverage_is_per_device_and_metric(tmp_path):
    e, devices = load(
        tmp_path,
        sources=SOURCES,
        aggregated=[
            aggregated_row(
                "daily_report", "steps", 1767225600, {"steps": 4000, "distance": 2800}, sid=sid
            )
            for sid in ("900", "902")
        ],
    )
    raw = {
        "steps": [
            {
                "device_id": devices["900"].device_id,
                "start_utc": "2026-01-01T12:00:00Z",
                "utc_offset": "+01:00",
            }
        ]
    }
    out = map_vendor_daily(e, devices, raw)
    assert len(out) == 3
    assert {(r["device_id"], r["metric"]) for r in out} == {
        (devices["900"].device_id, "distance"),
        (devices["902"].device_id, "steps"),
        (devices["902"].device_id, "distance"),
    }
