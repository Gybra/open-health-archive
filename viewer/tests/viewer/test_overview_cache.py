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


def test_period_change_reuses_source_overlap_audits(viewer_app):
    from dashboard_nav import open_page

    open_page(viewer_app, "Heart")
    with patch("healthviz.dashboard.charts.resolve_rows", wraps=resolve_rows) as resolve:
        viewer_app.segmented_control(key="preset").set_value("7d").run()
    assert not viewer_app.error
    assert resolve.call_count == 0


def test_workout_rerun_reuses_resolved_workouts_and_max_hr(viewer_app):
    from dashboard_nav import activity_view

    from healthviz.analysis import heart

    activity_view(viewer_app, "Workouts")
    with (
        patch("healthviz.analysis.heart.resolve_rows", wraps=resolve_rows) as resolve,
        patch("healthviz.dashboard.workouts.max_hr", wraps=heart.max_hr) as maximum,
    ):
        viewer_app.run()
    assert not viewer_app.exception and not viewer_app.error
    assert (resolve.call_count, maximum.call_count) == (0, 0)
