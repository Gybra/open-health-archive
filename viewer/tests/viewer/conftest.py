import sys
from pathlib import Path

import pytest
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
    return AppTest.from_file(str(app), default_timeout=30).run()
