from unittest.mock import patch

from healthviz.analysis.sources import resolve_rows
from healthviz.settings import Settings, save_settings


def test_period_rerun_reuses_overview_source_context(viewer_app):
    with patch("healthviz.dashboard.context.resolve_rows", wraps=resolve_rows) as resolve:
        viewer_app.run()
    assert not viewer_app.error
    assert resolve.call_count == 0


def test_settings_change_invalidates_overview_context(viewer_app, tmp_path):
    save_settings(tmp_path / "config.toml", Settings(worn_hours_threshold=11))
    with patch("healthviz.dashboard.context.resolve_rows", wraps=resolve_rows) as resolve:
        viewer_app.run()
    assert not viewer_app.error
    assert resolve.call_count == 2
