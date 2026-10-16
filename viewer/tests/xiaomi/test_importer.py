from zoneinfo import ZoneInfo

import pytest
from fixture_archive import GPX
from test_sessions import sleep_value, workout_value
from test_writer import snapshot
from xiaomi_export import aggregated_row, fitness_row, sport_row, track_row, write_export

from healthviz.archive.validate import validate_archive
from healthviz.cli import main
from healthviz.xiaomi.importer import import_xiaomi
from healthviz.xiaomi.source import ExportError

ROME = ZoneInfo("Europe/Rome")


def synthetic_export(root):
    return write_export(
        root,
        fitness=[
            fitness_row("heart_rate", 1767258000, {"bpm": 61}),
            fitness_row("steps", 1767258000, {"steps": 80, "distance": 55, "calories": 3}),
            fitness_row("calories", 1767258000, {"calories": 4}),
            fitness_row("sleep", 1767250800, sleep_value()),
            fitness_row("resting_heart_rate", 1767225600, {"date_time": 1767225600, "bpm": 55}),
            fitness_row("spo2", 1767258000, {"spo2": 98}),
            fitness_row("weight", 1767258000, {"weight": 65.0}, sid="901"),
        ],
        sport=[sport_row("outdoor_walking", 1767258000, workout_value())],
        tracks=[track_row(1767258000, "https://example.invalid/SECRET")],
        aggregated=[
            aggregated_row("daily_report", "steps", 1767312000, {"steps": 4000, "distance": 2800})
        ],
    )


def test_full_import_and_idempotency(tmp_path):
    export = synthetic_export(tmp_path / "input")
    output = tmp_path / "output"
    result = import_xiaomi(export, output, zone=ROME, fetch=lambda url: GPX)
    assert result.counts["heart_rate"] == 1 and result.counts["workouts"] == 1
    assert result.tracks_linked == 1 and result.tracks_missing == 0
    assert result.warnings == [] and validate_archive(output) == []
    before = snapshot(output)

    def never(url):
        raise AssertionError("should reuse track")

    import_xiaomi(export, output, zone=ROME, fetch=never)
    assert snapshot(output) == before


def test_output_cannot_overwrite_input(tmp_path):
    export = synthetic_export(tmp_path / "input")
    with pytest.raises(ExportError):
        import_xiaomi(export, export / "archive", zone=ROME)


def test_cli_synthetic_without_network(tmp_path, capsys):
    export = synthetic_export(tmp_path / "input")
    tracks = tmp_path / "tracks"
    tracks.mkdir()
    (tracks / "1767258000.gpx").write_bytes(GPX)
    assert (
        main(
            [
                "import",
                "xiaomi",
                str(export),
                "--out",
                str(tmp_path / "a"),
                "--tracks-dir",
                str(tracks),
                "--timezone",
                "Europe/Rome",
            ]
        )
        == 0
    )
    assert "heart_rate: 1" in capsys.readouterr().out
    assert (
        main(
            [
                "import",
                "xiaomi",
                str(tmp_path / "missing"),
                "--out",
                str(tmp_path / "b"),
                "--timezone",
                "Europe/Rome",
            ]
        )
        == 1
    )
    out = capsys.readouterr()
    assert "Traceback" not in out.err


def test_malformed_values_are_redacted(tmp_path, capsys):
    rows = [
        fitness_row("SECRET_KEY", 1767225600, {"SECRET_FIELD": 4242}),
        fitness_row("heart_rate", 1767225600, {"bpm": 4242}),
        fitness_row("heart_rate", 1767225660, {"bpm": "SECRET_VALUE"}),
    ]
    rows[1]["Value"] = '{"bpm": 4242'
    export = write_export(tmp_path / "input", fitness=rows)
    assert (
        main(
            [
                "import",
                "xiaomi",
                str(export),
                "--out",
                str(tmp_path / "a"),
                "--timezone",
                "Europe/Rome",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert "SECRET" not in output.out + output.err
    assert "4242" not in output.out + output.err
    assert "900" not in output.out + output.err


def test_cli_config_supplies_the_fallback_timezone(tmp_path):
    export = synthetic_export(tmp_path / "input")
    tracks = tmp_path / "tracks"
    tracks.mkdir()
    (tracks / "1767258000.gpx").write_bytes(GPX)
    config = tmp_path / "config.toml"
    config.write_text('default_timezone = "Europe/Rome"\n')
    base = ["import", "xiaomi", str(export), "--tracks-dir", str(tracks)]

    assert main([*base, "--out", str(tmp_path / "zone"), "--timezone", "Europe/Rome"]) == 0
    assert main([*base, "--out", str(tmp_path / "settings"), "--config", str(config)]) == 0

    def heart_rows(root):
        return [path.read_text() for path in sorted((root / "heart_rate").glob("*.csv"))]

    assert heart_rows(tmp_path / "settings") == heart_rows(tmp_path / "zone")


def test_cli_without_a_timezone_or_config_fails(tmp_path, capsys):
    export = synthetic_export(tmp_path / "input")

    assert main(["import", "xiaomi", str(export), "--out", str(tmp_path / "a")]) == 1
    assert "import failed: give --timezone or --config" in capsys.readouterr().err
