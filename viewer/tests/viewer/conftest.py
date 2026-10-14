import sys
from pathlib import Path

import pytest
from dashboard_nav import show_all
from streamlit.testing.v1 import AppTest
from viewer_archive import write_viewer_archive

import healthviz


@pytest.fixture
def viewer_app(tmp_path, monkeypatch):
    app = Path(healthviz.__file__).parent / "dashboard/app.py"
    assert app.exists(), "dashboard is missing"
    root = write_viewer_archive(tmp_path / "archive")
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--archive", str(root), "--config", str(tmp_path / "config.toml"), "--offline"],
    )
    # The fixture spans ten months; most tests look at all of it.
    return show_all(AppTest.from_file(str(app), default_timeout=30).run())


@pytest.fixture(autouse=True)
def no_background_results(monkeypatch):
    """Viewer tests stay single-process; test_read_model_background.py covers the real start."""
    from healthviz import read_model

    if hasattr(read_model, "start_precompute"):
        monkeypatch.setattr(read_model, "start_precompute", lambda *args, **kwargs: None)
