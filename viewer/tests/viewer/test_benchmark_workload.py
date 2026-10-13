import importlib
import importlib.util

from healthviz.archive.reader import load_archive
from healthviz.archive.validate import validate_archive


def test_benchmark_generator_builds_only_valid_synthetic_archive(tmp_path):
    assert importlib.util.find_spec("benchmark_read_model"), "synthetic benchmark is missing"
    benchmark = importlib.import_module("benchmark_read_model")
    root = tmp_path / "archive"
    benchmark.generate_archive(root, sample_count=48)
    assert not validate_archive(root)
    tables = load_archive(root)
    assert len(tables["heart_rate"]) == 48
    assert set(tables["devices"].vendor) == {"Fictional"}
    assert set(tables["heart_rate"].ingest) == {"synthetic_export"}
