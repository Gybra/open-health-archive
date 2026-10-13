"""Opt-in synthetic startup benchmark; prints only timings, counts and byte sizes."""

import argparse
import json
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def generate_archive(root: Path, *, sample_count=280_000):
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from copy import deepcopy

    from fixture_archive import FIXTURE_DEVICES, fixture_row

    from healthviz.archive.schema import TABLES
    from healthviz.archive.validate import validate_archive
    from healthviz.archive.writer import write_archive

    tables = {name: [] for name in TABLES if name != "devices"}
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def stamp(index):
        return (start + timedelta(seconds=30 * index)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for index in range(sample_count):
        tables["heart_rate"].append(
            fixture_row(
                "heart_rate",
                time_utc=stamp(index),
                utc_offset="+01:00",
                bpm="60",
                device_id="fixture-watch" if index % 2 else "fixture-phone",
                ingest="synthetic_export",
                record_id=f"sample-{index}",
            )
        )
    for name, stride, field, value in [
        ("steps", 20, "count", "10"),
        ("distance", 30, "distance_m", "5"),
    ]:
        for index in range(0, sample_count, stride):
            tables[name].append(
                fixture_row(
                    name,
                    start_utc=stamp(index),
                    end_utc=stamp(index + 2),
                    utc_offset="+01:00",
                    device_id="fixture-watch",
                    ingest="synthetic_export",
                    record_id=f"interval-{index}",
                    **{field: value},
                )
            )
    tracks = {}
    for day in range(max(1, (sample_count * 30 + 86399) // 86400)):
        date = start + timedelta(days=day)
        local = date.strftime("%Y-%m-%d")
        tables["resting_heart_rate"].append(
            fixture_row(
                "resting_heart_rate",
                date_local=local,
                bpm="54",
                computed_by="vendor",
                device_id="fixture-watch",
                ingest="synthetic_export",
                record_id=f"resting-{day}",
            )
        )
        tables["sleep_sessions"].append(
            fixture_row(
                "sleep_sessions",
                session_id=f"night-{day}",
                start_utc=local + "T00:00:00Z",
                end_utc=local + "T09:00:00Z",
                utc_offset="+01:00",
                has_stages="false",
                is_complete="true",
                deep_min="120",
                light_min="300",
                rem_min="60",
                awake_min="60",
                computed_by="vendor",
                device_id="fixture-watch",
                ingest="synthetic_export",
                record_id=f"night-{day}",
            )
        )
        track = f"tracks/synthetic-{day}.gpx"
        tracks[track] = (
            "<gpx><trk><trkseg>"
            + "".join(f'<trkpt lat="0" lon="{index / 100000:.5f}"/>' for index in range(500))
            + "</trkseg></trk></gpx>"
        ).encode()
        tables["workouts"].append(
            fixture_row(
                "workouts",
                workout_id=f"workout-{day}",
                type="walking",
                start_utc=local + "T10:00:00Z",
                end_utc=local + "T10:30:00Z",
                utc_offset="+01:00",
                duration_s="1800",
                distance_m="2000",
                track_file=track,
                device_id="fixture-watch",
                ingest="synthetic_export",
                record_id=f"workout-{day}",
            )
        )
    write_archive(root, tables, deepcopy(FIXTURE_DEVICES), tracks, "synthetic-benchmark")
    assert not validate_archive(root), "synthetic generator produced an invalid archive"
    return sum(len(frame) for frame in tables.values()) + len(FIXTURE_DEVICES)


def worker(args):
    if args.source:
        sys.path.insert(0, args.source)
    from streamlit.testing.v1 import AppTest

    import healthviz
    from healthviz.analysis import daily as analysis
    from healthviz.archive import reader
    from healthviz.settings import Settings, save_settings

    phases = {}
    pre_cleanup_bytes = 0

    def instrument(module, attribute, name):
        original = getattr(module, attribute)

        def timed(*arguments, **keywords):
            started = time.perf_counter()
            try:
                return original(*arguments, **keywords)
            finally:
                phases[name] = phases.get(name, 0) + time.perf_counter() - started

        setattr(module, attribute, timed)

    instrument(analysis, "daily_summary", "analysis")
    if hasattr(reader, "verify_snapshot"):
        instrument(reader, "verify_snapshot", "source_verification")
        from healthviz import read_model, read_model_store

        instrument(read_model, "file_checksum", "db_checksum")
        instrument(read_model_store, "read_frames", "db_materialization")
        original_cleanup = read_model.cleanup

        def observed_cleanup(cache, keep):
            nonlocal pre_cleanup_bytes
            pre_cleanup_bytes = max(
                pre_cleanup_bytes, sum(p.stat().st_size for p in cache.rglob("*") if p.is_file())
            )
            return original_cleanup(cache, keep)

        read_model.cleanup = observed_cleanup
    with tempfile.TemporaryDirectory() as config_dir:
        config = Path(config_dir) / "config.toml"
        sys.argv = ["app.py", "--archive", args.archive, "--config", str(config), "--offline"]
        if args.cache:
            sys.argv.extend(["--cache-dir", args.cache])
        app_file = str(Path(healthviz.__file__).parent / "dashboard/app.py")
        metrics = {}

        def measured(name, operation):
            before = time.perf_counter()
            app = operation()
            metrics[name] = time.perf_counter() - before
            assert not app.error and not app.exception, "synthetic viewer failed"
            return app

        app = measured("overview", lambda: AppTest.from_file(app_file, default_timeout=120).run())
        metrics.update({"overview_phase_" + name: elapsed for name, elapsed in phases.items()})
        measured("new_session", lambda: AppTest.from_file(app_file, default_timeout=120).run())
        dates = app.session_state["snapshot"][2].date_local
        measured(
            "period_rerun", lambda: app.date_input[0].set_value((dates.min(), dates.min())).run()
        )
        app.date_input[0].set_value((dates.min(), dates.max())).run()
        measured("map_first", lambda: app.selectbox(key="page").select("Map").run())
        measured("map_cached", app.run)
        selector = next(item for item in app.multiselect if item.label == "Activity types")
        measured("map_filter", lambda: selector.set_value([]).run())
        app.selectbox(key="page").select("Overview").run()
        save_settings(config, Settings(worn_hours_threshold=11))
        measured("settings_rebuild", app.run)
        metrics["pre_cleanup_bytes"] = pre_cleanup_bytes
        metrics["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metrics["cache_bytes"] = (
            sum(p.stat().st_size for p in Path(args.cache).rglob("*") if p.is_file())
            if args.cache
            else 0
        )
        print(json.dumps(metrics))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--archive")
    parser.add_argument("--cache")
    parser.add_argument("--source")
    parser.add_argument("--baseline-source")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--samples", type=int, default=280_000)
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    assert args.trials >= 1 and args.samples >= 1
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        archive = root / "archive"
        rows = generate_archive(archive, sample_count=args.samples)
        observations = {}
        for mode in ("baseline", "memory", "cache_build", "cache_hit"):
            if mode == "baseline" and not args.baseline_source:
                continue
            observations[mode] = []
            for trial in range(args.trials):
                cache = root / ("cache-hit" if mode == "cache_hit" else f"cache-{mode}-{trial}")
                if mode.startswith("cache"):
                    cache.mkdir(mode=0o700, exist_ok=True)
                    # A prior settings-rebuild trial must not turn the next hit into a miss.
                    from healthviz.read_model import load_read_model
                    from healthviz.settings import Settings

                    if mode == "cache_hit":
                        load_read_model(
                            archive, Settings(), cache_dir=cache, config=root / "warm/config.toml"
                        )
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--archive",
                    str(archive),
                ]
                if mode.startswith("cache"):
                    command.extend(["--cache", str(cache)])
                if mode == "baseline":
                    command.extend(["--source", args.baseline_source])
                child = subprocess.run(command, capture_output=True, text=True, timeout=240)
                assert child.returncode == 0, f"synthetic benchmark worker failed: {mode}"
                observations[mode].append(json.loads(child.stdout))
                if mode != "cache_hit" and cache.exists():
                    shutil.rmtree(cache)
        summary = {}
        for mode, trials in observations.items():
            summary[mode] = {
                metric: {
                    "median": statistics.median(t[metric] for t in trials),
                    "min": min(t[metric] for t in trials),
                    "max": max(t[metric] for t in trials),
                }
                for metric in trials[0]
            }
        print(
            json.dumps(
                {
                    "synthetic_rows": rows,
                    "trials": args.trials,
                    "os_file_cache": "not evicted; independent worker processes",
                    "results": summary,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
