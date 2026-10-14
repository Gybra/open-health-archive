import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from dashboard_nav import activity_view, open_page, set_period
from streamlit.testing.v1 import AppTest
from viewer_archive import write_viewer_archive

import healthviz
from healthviz import read_model
from healthviz.dashboard.context import PAGES

APP = str(Path(healthviz.__file__).parent / "dashboard/app.py")


def rendered(app):
    """Rendered protos: chart specs, Arrow tables, texts, decks and content-hashed downloads."""
    assert not app.exception and not app.error
    found = []

    def walk(node):
        proto = getattr(node, "proto", None)
        # The opt-in privacy notice is the one intended difference between modes.
        notice = type(node).__name__ == "Caption" and proto.body.startswith("Persistent local")
        if proto is not None and hasattr(proto, "SerializeToString") and not notice:
            if [field.name for field, _ in proto.ListFields()] == ["json"]:
                spec = json.loads(proto.json)
                for layer in spec.get("layers", []):
                    layer.pop("id", None)  # pydeck draws a random id per render
                found.append((type(node).__name__, json.dumps(spec, sort_keys=True).encode()))
            else:
                found.append((type(node).__name__, proto.SerializeToString(deterministic=True)))
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(app._tree)
    return found


def tour(app):
    daily = app.session_state["snapshot"][2]
    first, last = daily.date_local.min(), daily.date_local.max()
    views = []
    for period in [(first, last), (first, first + (last - first) / 2)]:
        set_period(app, *period)
        for page in PAGES:
            open_page(app, page)
            views.append((page, period, rendered(app)))
        for view in ("Daily", "Workouts", "Routes"):
            activity_view(app, view)
            views.append((view, period, rendered(app)))
        selector = next(m for m in app.multiselect if m.label == "Activity types")
        selector.set_value([]).run()
        views.append(("Routes filtered", period, rendered(app)))
        selector.set_value(selector.options).run()
    return views


def session(monkeypatch, root, config, cache=None):
    argv = ["app.py", "--archive", str(root), "--config", str(config), "--offline"]
    if cache is not None:
        argv += ["--cache-dir", str(cache)]
    monkeypatch.setattr(sys, "argv", argv)
    return AppTest.from_file(APP, default_timeout=60).run()


def realistic_archive(root):
    from benchmark_read_model import generate_archive

    generate_archive(root, sample_count=40_000)
    return root


@pytest.mark.parametrize("build", [write_viewer_archive, realistic_archive])
def test_every_page_renders_identically_from_persistent_hit(tmp_path, monkeypatch, build):
    root = build(tmp_path / "archive")
    config = tmp_path / "config/config.toml"
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    expected = tour(session(monkeypatch, root, config))
    session(monkeypatch, root, config, cache)
    recompute = AssertionError("persistent hit must not recompute startup data")
    with (
        patch.object(read_model, "load_archive", side_effect=recompute),
        patch.object(read_model, "daily_summary", side_effect=recompute),
    ):
        hit = session(monkeypatch, root, config, cache)
    actual = tour(hit)
    assert [view[:2] for view in actual] == [view[:2] for view in expected]
    for (page, period, want), (_, _, got) in zip(expected, actual, strict=True):
        assert got == want, f"{page} differs for period ending {period[1]}"
    assert len({view[2].__repr__() for view in expected}) > len(PAGES), "tour must vary output"
