import importlib

import pytest
from dashboard_nav import activity_view


@pytest.mark.parametrize("view", ["Workouts", "Routes"])
def test_activity_views_render(viewer_app, view):
    activity_view(viewer_app, view)
    assert not viewer_app.exception
    assert not viewer_app.error


def test_no_gps_no_elevation_no_profile(viewer_app):
    assert importlib.util.find_spec("healthviz.dashboard.workouts"), "workout page is missing"
    activity_view(viewer_app, "Workouts")
    assert not viewer_app.error
    viewer_app.selectbox(key="workout").set_value(("synthetic", "gym")).run()
    assert not viewer_app.error
    assert any("No GPS" in x.value for x in viewer_app.info)


def test_heatmap_uses_only_selected_workouts(viewer_app):
    assert importlib.util.find_spec("healthviz.dashboard.maps"), "map page is missing"
    activity_view(viewer_app, "Routes")
    assert not viewer_app.error
    type_filter = next(w for w in viewer_app.multiselect if w.label == "Activity types")
    type_filter.set_value(["strength_training"]).run()
    assert not viewer_app.error
    assert any("No valid tracks" in x.value for x in viewer_app.info)
