import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def launcher():
    assert importlib.util.find_spec("healthviz.launch"), "viewer launcher is missing"
    return importlib.import_module("healthviz.launch")


@pytest.mark.parametrize(
    "container,lan,address",
    [(False, False, "127.0.0.1"), (True, False, "0.0.0.0"), (False, True, "0.0.0.0")],
)
def test_launcher_addresses_and_privacy(tmp_path, container, lan, address):
    mod = launcher()
    with patch(
        "healthviz.launch.subprocess.run", return_value=SimpleNamespace(returncode=0)
    ) as child:
        assert (
            mod.view(
                Path("/archive"),
                config=tmp_path / "config.toml",
                container=container,
                lan=lan,
                offline=True,
            )
            == 0
        )
    argv = child.call_args.args[0]
    assert f"--server.address={address}" in argv
    assert "--browser.gatherUsageStats=false" in argv
    assert "--client.showErrorDetails=none" in argv
    assert "--server.fileWatcherType=none" in argv
    assert "--offline" in argv


def test_cache_dir_is_forwarded_explicitly(tmp_path):
    with patch(
        "healthviz.launch.subprocess.run", return_value=SimpleNamespace(returncode=0)
    ) as child:
        assert (
            launcher().view(
                Path("/archive"),
                config=tmp_path / "config.toml",
                cache_dir=Path("/cache"),
                container=True,
                offline=True,
            )
            == 0
        )
    argv = child.call_args.args[0]
    assert argv[argv.index("--cache-dir") + 1] == "/cache"
    assert "--offline" in argv and "--server.port=8501" in argv


def test_launcher_failure_is_redacted(tmp_path, capsys):
    mod = launcher()
    with patch("healthviz.launch.subprocess.run", side_effect=OSError("PRIVATE-SENTINEL")):
        assert mod.view(Path("/archive"), config=tmp_path / "config.toml") == 1
    assert "PRIVATE-SENTINEL" not in capsys.readouterr().err
