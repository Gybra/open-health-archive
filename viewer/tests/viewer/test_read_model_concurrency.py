import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
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


@pytest.mark.parametrize("phase", ["disk-full", "database", "pointer"])
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
        if phase == "disk-full":

            def disk_full(path, *args):
                import errno

                # A real ENOSPC mid-write leaves a partial candidate WAL behind.
                Path(str(path) + ".wal").write_bytes(b"partial synthetic wal")
                raise OSError(errno.ENOSPC, "PRIVATE-SENTINEL")

            context.setattr(mod.store, "write_frames", disk_full)
        with pytest.raises(mod.ReadModelError) as error:
            mod.load_read_model(
                root, replace(Settings(), worn_hours_threshold=11), cache_dir=cache, config=config
            )
        assert "PRIVATE-SENTINEL" not in str(error.value)
        assert not list(cache.glob(".building-*")), "failed builds must not keep plaintext"
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


def test_checkpoint_failure_keeps_previous_publication(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    first = mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    pointer = (cache / "current.json").read_bytes()
    original = mod.store.connection

    class FailingCheckpoint:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            self.inner = self.conn.__enter__()
            return self

        def __exit__(self, *exc):
            return self.conn.__exit__(*exc)

        def execute(self, sql, *args):
            if sql == "CHECKPOINT":
                raise mod.duckdb.IOException("PRIVATE-SENTINEL")
            return self.inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def connection(path, *, read_only):
        conn = original(path, read_only=read_only)
        return conn if read_only else FailingCheckpoint(conn)

    with monkeypatch.context() as context:
        context.setattr(mod.store, "connection", connection)
        with pytest.raises(mod.ReadModelError) as error:
            mod.load_read_model(
                root, replace(Settings(), worn_hours_threshold=11), cache_dir=cache, config=config
            )
    assert "PRIVATE-SENTINEL" not in str(error.value)
    assert (cache / "current.json").read_bytes() == pointer
    assert not list(cache.glob(".building-*"))
    pd.testing.assert_frame_equal(
        first.daily, mod.load_read_model(root, Settings(), cache_dir=cache, config=config).daily
    )


def test_cleanup_failure_does_not_fail_a_completed_publication(tmp_path, monkeypatch):
    mod = module()
    root, cache, config = prepare(tmp_path)
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    old = cache / json.loads((cache / "current.json").read_bytes())["file"]
    original, listing = Path.unlink, Path.iterdir

    def busy(path, *args, **kwargs):
        if path == old:
            raise OSError("PRIVATE-SENTINEL")
        return original(path, *args, **kwargs)

    changed = replace(Settings(), worn_hours_threshold=11)
    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", busy)
        published = mod.load_read_model(root, changed, cache_dir=cache, config=config)
    assert old.exists(), "failed cleanup leaves the old generation for a later retry"
    with patch.object(mod, "load_archive", side_effect=AssertionError("must be a hit")):
        hit = mod.load_read_model(root, changed, cache_dir=cache, config=config)
    pd.testing.assert_frame_equal(published.daily, hit.daily)
    stranded = cache / json.loads((cache / "current.json").read_bytes())["file"]
    with monkeypatch.context() as context:
        context.setattr(Path, "unlink", busy)
        # Visit the undeletable copy first so the remaining entries depend on per-entry handling.
        context.setattr(Path, "iterdir", lambda path: iter(sorted(listing(path), key=old.__ne__)))
        mod.load_read_model(
            root, replace(Settings(), worn_hours_threshold=12), cache_dir=cache, config=config
        )
    assert old.exists() and not stranded.exists(), "one failure must not strand other copies"
    mod.load_read_model(root, Settings(), cache_dir=cache, config=config)
    assert not old.exists(), "the next publication retries cleanup"
    assert len(list(cache.glob("generation-*.duckdb"))) == 1


APP_WORKER = """
import sys
from pathlib import Path
from unittest.mock import patch
from healthviz.server import deny_network
sys.addaudithook(deny_network)
from streamlit.testing.v1 import AppTest
import healthviz
from healthviz import read_model
sys.argv = ["app.py", "--archive", sys.argv[1], "--config", sys.argv[2], "--offline",
    "--cache-dir", sys.argv[3]]
app_file = str(Path(healthviz.__file__).parent / "dashboard/app.py")
with patch.object(read_model, "load_archive", side_effect=AssertionError("reparsed")), \\
        patch.object(read_model, "daily_summary", side_effect=AssertionError("recomputed")):
    app = AppTest.from_file(app_file, default_timeout=60).run()
assert not app.exception and not app.error, "cached app failed"
assert app.get("plotly_chart"), "Overview charts missing"
print("rendered")
"""


def test_new_process_renders_app_from_persistent_cache(tmp_path):
    root, cache, config = prepare(tmp_path)
    module().load_read_model(root, Settings(), cache_dir=cache, config=config)
    child = subprocess.run(
        [sys.executable, "-c", APP_WORKER, str(root), str(config), str(cache)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert child.returncode == 0, "cached app worker failed"
    assert child.stdout.strip() == "rendered"
