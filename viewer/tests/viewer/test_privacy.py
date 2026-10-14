from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import streamlit as st
from dashboard_nav import start
from viewer_archive import write_viewer_archive

from healthviz.archive.gpx import validate_gpx
from healthviz.archive.reader import ArchiveReadError, load_archive
from healthviz.launch import view


def test_private_cell_does_not_enter_diagnostics(tmp_path, capsys, caplog):
    root = write_viewer_archive(tmp_path)
    path = root / "heart_rate/2026-01.csv"
    path.write_text(path.read_text().replace(",60,", ",PRIVATE-SENTINEL,"))
    with pytest.raises(ArchiveReadError) as error:
        load_archive(root)
    output = capsys.readouterr()
    assert "PRIVATE-SENTINEL" not in str(error.value) + output.out + output.err + caplog.text


def test_utf16_dtd_is_rejected():
    xml = '<!DOCTYPE gpx [<!ENTITY private "PRIVATE-SENTINEL">]><gpx><name>&private;</name></gpx>'
    with pytest.raises(ValueError):
        validate_gpx(xml.encode("utf-16"))


def test_launcher_does_not_discover_public_ip(tmp_path):
    with patch(
        "healthviz.launch.subprocess.run", return_value=SimpleNamespace(returncode=0)
    ) as child:
        assert view(Path("/archive"), config=tmp_path / "config.toml", container=True) == 0
    assert "--browser.serverAddress=127.0.0.1" in child.call_args.args[0]
    assert "--client.toolbarMode=minimal" in child.call_args.args[0]


def test_changed_snapshot_does_not_display_stale_cache(viewer_app, tmp_path):
    path = tmp_path / "archive/heart_rate/2026-01.csv"
    path.write_text(path.read_text().replace(",60,", ",PRIVATE-SENTINEL,"))
    viewer_app.run()
    assert viewer_app.error
    assert "PRIVATE-SENTINEL" not in viewer_app.error[0].value
    assert "snapshot" not in viewer_app.session_state


def test_server_blocks_socket_and_dns_before_streamlit():
    import importlib
    import subprocess
    import sys

    assert importlib.util.find_spec("healthviz.server"), "startup network guard is missing"
    script = """
import socket, sys
from healthviz.server import deny_network
sys.addaudithook(deny_network)
for operation in (lambda: socket.socket().connect(('127.0.0.1', 9)),
                  lambda: socket.getaddrinfo('PRIVATE-SENTINEL.invalid', 80)):
    try:
        operation()
    except PermissionError as error:
        assert 'PRIVATE-SENTINEL' not in str(error)
    else:
        raise AssertionError('network attempt was allowed')
print('blocked')
"""
    child = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert child.returncode == 0
    assert child.stdout.strip() == "blocked"


def test_browser_tab_icon_is_drawn_locally(tmp_path, monkeypatch):
    # Without its own icon, Streamlit shows the page's Material icon in the browser tab and
    # the browser downloads it from fonts.gstatic.com, even offline.
    icons = []
    original = st.set_page_config

    def set_page_config(**options):
        icons.append(options.get("page_icon"))
        return original(**options)

    with patch.object(st, "set_page_config", set_page_config):
        app = start(monkeypatch, write_viewer_archive(tmp_path / "a"), tmp_path / "c.toml")
    assert not app.exception
    assert icons and all(
        isinstance(icon, str) and icon and not icon.startswith((":", "http")) for icon in icons
    )


def test_config_cannot_be_written_inside_archive(tmp_path):
    root = write_viewer_archive(tmp_path)
    manifest = (root / "manifest.json").read_bytes()
    assert view(root, config=root / "config.toml") == 1
    assert not (root / "config.toml").exists()
    assert (root / "manifest.json").read_bytes() == manifest


@pytest.mark.parametrize("boundary", ["gpx", "config", "duckdb"])
def test_private_values_are_redacted_at_every_read_boundary(tmp_path, capsys, caplog, boundary):
    import duckdb

    from healthviz.analysis.gps import read_track
    from healthviz.settings import SettingsError, load_settings

    root = write_viewer_archive(tmp_path / "archive")
    with pytest.raises((ValueError, SettingsError, ArchiveReadError)) as error:
        if boundary == "gpx":
            path = root / "tracks/walk.gpx"
            path.write_text(
                '<gpx><trk><trkseg><trkpt lat="PRIVATE-SENTINEL" lon="0"/></trkseg></trk></gpx>'
            )
            read_track(root, "tracks/walk.gpx")
        elif boundary == "config":
            path = tmp_path / "config.toml"
            path.write_text('max_hr = "PRIVATE-SENTINEL"')
            load_settings(path)
        else:
            with patch(
                "healthviz.archive.reader.duckdb.connect",
                side_effect=duckdb.Error("PRIVATE-SENTINEL"),
            ):
                load_archive(root)
    output = capsys.readouterr()
    assert "PRIVATE-SENTINEL" not in str(error.value) + output.out + output.err + caplog.text
