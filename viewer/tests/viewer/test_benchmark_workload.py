import importlib
import importlib.util

from healthviz.archive.reader import load_archive
from healthviz.archive.validate import validate_archive
from healthviz.settings import Settings


def test_benchmark_generator_builds_only_valid_synthetic_archive(tmp_path):
    assert importlib.util.find_spec("benchmark_read_model"), "synthetic benchmark is missing"
    benchmark = importlib.import_module("benchmark_read_model")
    root = tmp_path / "archive"
    benchmark.generate_archive(root, sample_count=48)
    assert not validate_archive(root)
    tables = load_archive(root)
    assert set(tables["devices"].vendor) == {"Fictional"}
    assert set(tables["heart_rate"].ingest) <= {"synthetic_export", "synthetic_phone"}


def test_benchmark_workload_exercises_realistic_archive_shapes(tmp_path):
    from healthviz.analysis.daily import daily_summary

    benchmark = importlib.import_module("benchmark_read_model")
    root = tmp_path / "archive"
    benchmark.generate_archive(root, sample_count=40_000)
    assert not validate_archive(root)
    tables = load_archive(root)
    hr = tables["heart_rate"]
    assert {"+01:00", "+02:00", "+05:30"} <= set(hr.utc_offset), "DST and travel offsets"
    assert hr.device_id.nunique() == 3 and hr.ingest.nunique() == 2, "independent sources"
    assert set(tables["resting_heart_rate"].computed_by) == {"vendor", "app"}, "method epochs"
    sleep = tables["sleep_sessions"]
    assert sleep.has_stages.any() and not sleep.has_stages.all()
    assert sleep.is_complete.eq(False).any()
    assert not tables["sleep_stages"].empty
    workouts = tables["workouts"]
    assert workouts.type.nunique() >= 3
    assert workouts.track_file.notna().any() and workouts.track_file.isna().any()
    assert not tables["weight"].empty and not tables["spo2"].empty
    daily = daily_summary(tables, tables["devices"], Settings())
    assert daily.complete.any() and not daily.complete.all(), "gaps reduce coverage"
    assert daily.worn_hours.lt(12).any(), "a day without the watch leaves phone-only hours"
