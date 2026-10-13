import urllib.error

import pytest
from fixture_archive import GPX
from test_sessions import workout_value
from xiaomi_export import load, sport_row, track_row

from healthviz.xiaomi.tracks import collect_tracks, download
from healthviz.xiaomi.workouts import map_workouts

TIME = 1767258000
URL = "https://example.invalid/track?Signature=SECRET"


def setup(root):
    export, devices = load(
        root,
        sport=[sport_row("outdoor_walking", TIME, workout_value())],
        tracks=[track_row(TIME, URL)],
    )
    return export, map_workouts(export, devices)


def test_download_and_link(tmp_path):
    e, w = setup(tmp_path / "x")
    tracks = collect_tracks(e, w, tmp_path / "archive", None, fetch=lambda url: GPX)
    assert tracks == {"tracks/xiaomi-outdoor_walking-1767258000.gpx": GPX}
    assert w[0]["track_file"] == "tracks/xiaomi-outdoor_walking-1767258000.gpx"


def test_local_and_existing_no_download(tmp_path):
    def forbidden(url):
        raise AssertionError("must not download")

    e, w = setup(tmp_path / "x")
    local = tmp_path / "local"
    local.mkdir()
    (local / f"{TIME}.gpx").write_bytes(GPX)
    tracks = collect_tracks(e, w, tmp_path / "archive", local, fetch=forbidden)
    path = tmp_path / "archive" / next(iter(tracks))
    path.parent.mkdir(parents=True)
    path.write_bytes(GPX)
    assert collect_tracks(e, w, tmp_path / "archive", None, fetch=forbidden) == {}


def test_expired_link_redacted(tmp_path):
    def fetch(url):
        raise urllib.error.HTTPError(url, 403, "SECRET", None, None)

    e, w = setup(tmp_path / "x")
    assert collect_tracks(e, w, tmp_path / "archive", None, fetch=fetch) == {}
    assert w[0]["track_file"] == "" and "SECRET" not in str(e.warnings)
    assert any("HTTPError" in x for x in e.warnings)


@pytest.mark.parametrize(
    "body", [b"<html/>", b"<notgpx/>", b"broken", b'<!DOCTYPE gpx [<!ENTITY x "a">]><gpx/>']
)
def test_non_gpx(tmp_path, body):
    e, w = setup(tmp_path / "x")
    assert collect_tracks(e, w, tmp_path / "archive", None, fetch=lambda url: body) == {}
    assert w[0]["track_file"] == "" and e.warnings


def test_no_workout(tmp_path):
    e, _ = setup(tmp_path / "x")
    assert collect_tracks(e, [], tmp_path / "a", None, fetch=lambda url: GPX) == {}
    assert any("no workout" in x for x in e.warnings)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://localhost/a", "https://fds.api.xiaomi.com.evil.invalid/a"]
)
def test_download_url_boundary(url):
    with pytest.raises(ValueError):
        download(url)
