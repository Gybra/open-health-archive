"""Opt-in synthetic startup benchmark; prints only timings, counts and byte sizes."""

import argparse
import json
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def generate_archive(root: Path, *, sample_count=280_000):
    """Fictional archive with DST/travel offsets, gaps, overlapping sources and method epochs."""
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from copy import deepcopy

    from fixture_archive import FIXTURE_DEVICES, fixture_row

    from healthviz.archive.schema import TABLES
    from healthviz.archive.validate import validate_archive
    from healthviz.archive.writer import write_archive

    tables = {name: [] for name in TABLES if name != "devices"}
    start = datetime(2026, 3, 20, tzinfo=UTC)
    dst = datetime(2026, 3, 29, 1, tzinfo=UTC)
    days = max(1, (sample_count * 30 + 86399) // 86400)

    def at(day, seconds=0):
        return start + timedelta(days=day, seconds=seconds)

    def stamp(instant):
        return instant.strftime("%Y-%m-%dT%H:%M:%SZ")

    def offset(instant):
        if (instant - start).days in (11, 12):
            return "+05:30"
        return "+02:00" if instant >= dst else "+01:00"

    def worn(instant):
        day = (instant - start).days
        return day != 6 and not (day % 5 == 2 and instant.hour < 6)

    def add(name, instant, **fields):
        fields.setdefault("ingest", "synthetic_export")
        tables[name].append(fixture_row(name, utc_offset=offset(instant), **fields))

    def interval(name, instant, seconds, **fields):
        add(
            name,
            instant,
            start_utc=stamp(instant),
            end_utc=stamp(instant + timedelta(seconds=seconds)),
            **fields,
        )

    for index in range(sample_count):
        instant = at(0, 30 * index)
        if worn(instant):
            add(
                "heart_rate",
                instant,
                time_utc=stamp(instant),
                bpm=str(52 + index % 45),
                record_id=f"watch-{index}",
            )
            if index % 20 == 0:
                interval(
                    "steps", instant, 60, count=str(10 + index % 7), record_id=f"steps-{index}"
                )
                interval(
                    "distance",
                    instant,
                    60,
                    distance_m=str(5 + index % 3),
                    record_id=f"distance-{index}",
                )
    for day in range(days):
        local = (at(day) + timedelta(hours=1)).strftime("%Y-%m-%d")
        if day % 3 == 0:
            for minute in range(8 * 60, 20 * 60, 10):
                instant = at(day, minute * 60)
                phone = dict(device_id="fixture-phone", ingest="synthetic_phone")
                add(
                    "heart_rate",
                    instant,
                    time_utc=stamp(instant),
                    bpm="70",
                    record_id=f"phone-{day}-{minute}",
                    **phone,
                )
                if minute % 60 == 0:
                    interval(
                        "steps",
                        instant,
                        3600,
                        count="400",
                        record_id=f"phone-steps-{day}-{minute}",
                        **phone,
                    )
        if day in (4, 5):
            for index in range(0, 86400, 120):
                instant = at(day, index)
                add(
                    "heart_rate",
                    instant,
                    time_utc=stamp(instant),
                    bpm="64",
                    device_id="fixture-watch-2",
                    record_id=f"second-{day}-{index}",
                )
        for hour in range(24):
            instant = at(day, hour * 3600)
            if worn(instant):
                interval(
                    "calories",
                    instant,
                    3600,
                    kind="active",
                    kcal="12",
                    record_id=f"active-{day}-{hour}",
                )
                interval(
                    "calories",
                    instant,
                    3600,
                    kind="total",
                    kcal="85",
                    record_id=f"total-{day}-{hour}",
                )
        if day == 6:
            continue
        add_resting = dict(
            date_local=local, bpm=str(50 + day % 5), computed_by="vendor" if day < 7 else "app"
        )
        tables["resting_heart_rate"].append(
            fixture_row(
                "resting_heart_rate",
                ingest="synthetic_export",
                record_id=f"resting-{day}",
                **add_resting,
            )
        )
        night, staged = at(day), day % 2 == 0
        session = dict(
            session_id=f"night-{day}",
            start_utc=stamp(night),
            end_utc=stamp(night + timedelta(hours=7)),
            has_stages=str(staged).lower(),
            is_complete="false" if day % 9 == 4 else "true",
            computed_by="vendor",
            record_id=f"night-{day}",
        )
        if not staged:
            session.update(deep_min="90", light_min="240", rem_min="60", awake_min="30")
        add("sleep_sessions", night, **session)
        if staged:
            for part, (stage, begin, end) in enumerate(
                [
                    ("light", 0, 120),
                    ("deep", 120, 210),
                    ("rem", 210, 300),
                    ("awake", 300, 315),
                    ("light", 315, 420),
                ]
            ):
                tables["sleep_stages"].append(
                    fixture_row(
                        "sleep_stages",
                        ingest="synthetic_export",
                        session_id=f"night-{day}",
                        start_utc=stamp(night + timedelta(minutes=begin)),
                        end_utc=stamp(night + timedelta(minutes=end)),
                        stage=stage,
                        record_id=f"stage-{day}-{part}",
                    )
                )
        if day % 7 == 0:
            add(
                "weight",
                at(day, 6 * 3600),
                time_utc=stamp(at(day, 6 * 3600)),
                kg="70.5",
                record_id=f"weight-{day}",
            )
        if day % 2:
            add(
                "spo2",
                at(day, 3 * 3600),
                time_utc=stamp(at(day, 3 * 3600)),
                percent="97",
                record_id=f"spo2-{day}",
            )
    tracks = {}
    for day in range(days):
        begin = at(day, 10 * 3600)
        workout = dict(
            workout_id=f"workout-{day}",
            type=("walking", "running", "cycling")[day % 3],
            start_utc=stamp(begin),
            end_utc=stamp(begin + timedelta(minutes=30)),
            duration_s="1800",
            distance_m="2000",
            record_id=f"workout-{day}",
        )
        if day % 2 == 0:
            track = f"tracks/synthetic-{day}.gpx"
            tracks[track] = (
                "<gpx><trk><trkseg>"
                + "".join(f'<trkpt lat="0" lon="{index / 100000:.5f}"/>' for index in range(500))
                + "</trkseg></trk></gpx>"
            ).encode()
            workout["track_file"] = track
        add("workouts", begin, **workout)
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
    sampled_peak = 0
    sampling = threading.Event()

    def cache_bytes(cache):
        total = 0
        for path in Path(cache).rglob("*"):
            try:
                total += path.stat().st_size if path.is_file() else 0
            except OSError:  # files vanish while DuckDB/cleanup run
                pass
        return total

    def sample():
        nonlocal sampled_peak
        while not sampling.is_set():
            sampled_peak = max(sampled_peak, cache_bytes(args.cache))
            time.sleep(0.002)

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
            pre_cleanup_bytes = max(pre_cleanup_bytes, cache_bytes(cache))
            return original_cleanup(cache, keep)

        read_model.cleanup = observed_cleanup
    sampler = threading.Thread(target=sample, daemon=True)
    if args.cache:
        sampler.start()
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
        app.segmented_control(key="preset").set_value("Custom").run()
        period = app.date_input(key="period")
        measured("period_rerun", lambda: period.set_value((dates.min(), dates.min())).run())
        app.date_input(key="period").set_value((dates.min(), dates.max())).run()
        app.radio(key="page").set_value("Activity").run()
        view = app.segmented_control(key="activity_view")
        measured("map_first", lambda: view.set_value("Routes").run())
        measured("map_cached", app.run)
        selector = next(item for item in app.multiselect if item.label == "Activity types")
        measured("map_filter", lambda: selector.set_value([]).run())
        app.radio(key="page").set_value("Overview").run()
        save_settings(config, Settings(worn_hours_threshold=11))
        measured("settings_rebuild", app.run)
        sampling.set()
        if args.cache:
            sampler.join()
        # Sampling can miss sub-2 ms peaks; the pre-cleanup reading is a guaranteed lower bound.
        metrics["cache_peak_bytes"] = max(sampled_peak, pre_cleanup_bytes)
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
                    "disk_sampler": "2 ms cache-size sampler runs only in cache modes; "
                    "conservative bias against cached timings",
                    "results": summary,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
