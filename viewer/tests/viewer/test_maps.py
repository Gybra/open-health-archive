import importlib
import json
from pathlib import Path

import pandas as pd

import healthviz


def module():
    assert importlib.util.find_spec("healthviz.analysis.gps"), "GPS analysis is missing"
    return importlib.import_module("healthviz.analysis.gps")


def test_offline_deck_has_no_style_or_external_data():
    points = pd.DataFrame({"segment": [0, 0], "lat": [0.001, 0.002], "lon": [0.001, 0.002]})
    deck = module().map_deck(points, offline=True, coloring="density")
    assert deck.map_provider is None
    assert "https://" not in deck.to_json()
    assert "http://" not in deck.to_json()
    assert deck.layers


def test_map_style_contains_only_osm_tiles():
    module()
    path = Path(healthviz.__file__).parent / "dashboard/static/osm.json"
    style = json.loads(path.read_text())
    assert style["sources"]["osm"]["tiles"] == ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]
    assert "glyphs" not in style
    assert "sprites" not in style
    assert "OpenStreetMap" in style["sources"]["osm"]["attribution"]
