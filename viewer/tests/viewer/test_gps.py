import importlib

import pandas as pd
import pytest
from viewer_archive import write_viewer_archive


def module():
    assert importlib.util.find_spec("healthviz.analysis.gps"), "GPS analysis is missing"
    return importlib.import_module("healthviz.analysis.gps")


def test_track_bounds_paths_entities_and_time_formats(tmp_path):
    mod = module()
    root = write_viewer_archive(tmp_path)
    points = mod.read_track(root, "tracks/elevated-walk.gpx")
    assert points.elevation_m.iloc[0] == -5
    assert pd.isna(points.time.iloc[-1])
    for path in ["../outside.gpx", "/tmp/outside.gpx", "tracks/../../outside.gpx"]:
        with pytest.raises(ValueError):
            mod.read_track(root, path)
    target = root / "tracks/hostile.gpx"
    for xml in [
        b"<!DOCTYPE gpx><gpx/>",
        b'<gpx><trk><trkseg><trkpt lat="nan" lon="0"/></trkseg></trk></gpx>',
        b'<gpx><trk><trkseg><trkpt lat="0" lon="200"/></trkseg></trk></gpx>',
        b'<gpx><trk><trkseg><trkpt lat="0" lon="0">'
        b"<time>2026-01-01T00:00:00</time></trkpt></trkseg></trk></gpx>",
    ]:
        target.write_bytes(xml)
        with pytest.raises(ValueError):
            mod.read_track(root, "tracks/hostile.gpx")
    target.write_bytes(
        b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        b'<trkpt lat="0" lon="0"><time>2026-01-01T00:00:00.250+01:00</time>'
        b"</trkpt></trkseg></trk></gpx>"
    )
    assert mod.read_track(root, "tracks/hostile.gpx").time.iloc[0] == pd.Timestamp(
        "2025-12-31T23:00:00.250Z"
    )


def test_segments_gap_and_zero_distance_have_no_pace():
    mod = module()
    points = pd.DataFrame(
        {
            "segment": [0, 0, 1, 1],
            "lat": [0.0] * 4,
            "lon": [0.0, 0.001, 0.002, 0.002],
            "time": pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:30Z",
                    "2026-01-01T00:05:00Z",
                    "2026-01-01T00:05:30Z",
                ],
                utc=True,
            ),
            "elevation_m": [None] * 4,
        }
    )
    profile = mod.route_profile(points, pd.DataFrame())
    assert pd.isna(profile.pace_min_km.iloc[2])
    assert pd.isna(profile.pace_min_km.iloc[3])
    assert profile.distance_m.iloc[-1] == pytest.approx(111.195, abs=0.01)


def test_pace_uses_30_second_elapsed_window():
    mod = module()
    points = pd.DataFrame(
        {
            "segment": [0] * 4,
            "lat": [0.0] * 4,
            "lon": [0.0, 0.001, 0.002, 0.003],
            "time": pd.date_range("2026-01-01", periods=4, freq="10s", tz="UTC"),
            "elevation_m": [None] * 4,
        }
    )
    profile = mod.route_profile(points, pd.DataFrame())
    assert profile.distance_m.iloc[-1] == pytest.approx(333.585, abs=0.01)
    assert profile.pace_min_km.iloc[-1] == pytest.approx(1.4989, abs=0.001)
    assert pd.isna(profile.pace_min_km.iloc[1])


def test_nearest_hr_limit_and_elevation_absence(tmp_path):
    mod = module()
    points = mod.read_track(write_viewer_archive(tmp_path), "tracks/walk.gpx")
    hr = pd.DataFrame({"time_utc": [pd.Timestamp("2026-01-01T00:00:00Z")], "bpm": [70]})
    profile = mod.route_profile(points, hr)
    assert profile.bpm.iloc[1] == 70
    assert pd.isna(profile.bpm.iloc[2])
    assert profile.elevation_m.isna().all()


def test_point_children_match_in_any_namespace_first_one_wins():
    points = module().parse_track(
        b'<gpx xmlns="http://www.topografix.com/GPX/1/1" xmlns:x="urn:x"><trk>'
        b'<trkseg><trkpt lat="1" lon="2"><x:ele>7</x:ele><ele>9</ele>'
        b"<extensions><time>2026-01-01T05:00:00Z</time></extensions></trkpt>"
        b'<trkpt lat="3" lon="4"><time>2026-01-01T00:00:01Z</time><x:time>2026-01-02T00:00:00Z'
        b"</x:time></trkpt></trkseg>"
        b'<trkseg><trkpt lat="5" lon="6"><ele></ele></trkpt></trkseg></trk></gpx>'
    )
    assert points.segment.tolist() == [0, 0, 1]
    assert points.elevation_m.iloc[0] == 7
    assert pd.isna(points.elevation_m.iloc[1]) and pd.isna(points.elevation_m.iloc[2])
    assert pd.isna(points.time.iloc[0])
    assert points.time.iloc[1] == pd.Timestamp("2026-01-01T00:00:01Z")
