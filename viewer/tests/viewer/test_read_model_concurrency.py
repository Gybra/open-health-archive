import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

import pandas as pd
import pytest
from test_read_model import module, prepare

from healthviz.settings import Settings

WORKER = """
import sys
from pathlib import Path
from healthviz.server import deny_network
sys.addaudithook(deny_network)
from healthviz.read_model import load_read_model
from healthviz.settings import Settings
model = load_read_model(Path(sys.argv[1]), Settings(worn_hours_threshold=int(sys.argv[4])),
    cache_dir=Path(sys.argv[2]), config=Path(sys.argv[3]))
assert len(model.content_digest) == 64
print("ready")
"""


def test_threads_converge_on_one_complete_generation(tmp_path):
    mod = module()
    root, cache, config = prepare(tmp_path)
    barrier = threading.Barrier(4)

    def action(_):
        barrier.wait(timeout=10)
        return mod.load_read_model(root, Settings(), cache_dir=cache, config=config)

    with patch.object(mod, "derive", wraps=mod.derive) as build, ThreadPoolExecutor(4) as pool:
        models = list(pool.map(action, range(4)))
    assert build.call_count == 1
    for model in models[1:]:
        pd.testing.assert_frame_equal(model.daily, models[0].daily)
    assert len(list(cache.glob("generation-*.duckdb"))) == 1


def test_independent_processes_under_network_guard(tmp_path):
    root, cache, config = prepare(tmp_path)
    children = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, str(root), str(cache), str(config), str(n)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in (10, 10, 11)
    ]
    for child in children:
        output, error = child.communicate(timeout=30)
        assert child.returncode == 0, "synthetic cache worker failed"
        assert output.strip() == "ready"
        assert not error
    assert len(list(cache.glob("generation-*.duckdb"))) == 1


@pytest.mark.parametrize("phase", ["database", "pointer"])
def test_interrupted_publication_retains_previous_pointer_and_recovers(
    tmp_path, monkeypatch, phase
):
    mod = module()
    root, cache, config = prepare(tmp_path)
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    pointer = (cache / "current.json").read_bytes()
    original = mod.os.replace

    def fail(source, destination):
        if (phase == "database" and str(source).endswith(".duckdb")) or (
            phase == "pointer" and destination.name == "current.json"
        ):
            raise OSError("PRIVATE-SENTINEL")
        original(source, destination)

    with monkeypatch.context() as context:
        context.setattr(mod.os, "replace", fail)
        with pytest.raises(mod.ReadModelError) as error:
            mod.load_read_model(
                root, replace(Settings(), worn_hours_threshold=11), cache_dir=cache, config=config
            )
        assert "PRIVATE-SENTINEL" not in str(error.value)
    assert (cache / "current.json").read_bytes() == pointer
    recovered = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    pd.testing.assert_frame_equal(first.daily, recovered.daily)
    mod.load_read_model(
        root, replace(Settings(), worn_hours_threshold=11), cache_dir=cache, config=config
    )
    assert len(list(cache.glob("generation-*.duckdb"))) == 1
    assert not list(cache.glob(".pointer-*"))


def test_killed_builder_never_publishes_candidate(tmp_path):
    root, cache, config = prepare(tmp_path)
    code = WORKER.replace(
        "model = load_read_model",
        """
import os
import healthviz.read_model as mod
original = mod.os.replace
def kill(source, destination):
    original(source, destination)
    if str(source).endswith('.duckdb'):
        os._exit(17)
mod.os.replace = kill
model = load_read_model""",
    )
    child = subprocess.run(
        [sys.executable, "-c", code, str(root), str(cache), str(config), "10"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 17
    assert not (cache / "current.json").exists()
    module().load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert len(list(cache.glob("generation-*.duckdb"))) == 1
    assert "file" in json.loads((cache / "current.json").read_bytes())
