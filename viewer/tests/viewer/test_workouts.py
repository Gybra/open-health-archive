import importlib

import pytest


@pytest.mark.parametrize("page", ["Workouts", "Map"])
def test_all_seven_pages_render(viewer_app, page):
    assert importlib.util.find_spec("healthviz.dashboard.workouts"), "workout page is missing"
    viewer_app.selectbox(key="page").set_value(page).run()
    assert not viewer_app.exception
    assert not viewer_app.error


def test_no_gps_no_elevation_no_profile(viewer_app):
    assert importlib.util.find_spec("healthviz.dashboard.workouts"), "workout page is missing"
    viewer_app.selectbox(key="page").set_value("Workouts").run()
    assert not viewer_app.error
    widget = next(w for w in viewer_app.selectbox if w.label == "Workout")
    widget.set_value("gym").run()
    assert not viewer_app.error
    assert any("No GPS" in x.value for x in viewer_app.info)


def test_heatmap_uses_only_selected_workouts(viewer_app):
    assert importlib.util.find_spec("healthviz.dashboard.maps"), "map page is missing"
    viewer_app.selectbox(key="page").set_value("Map").run()
    assert not viewer_app.error
    type_filter = next(w for w in viewer_app.multiselect if w.label == "Activity types")
    type_filter.set_value(["strength_training"]).run()
    assert not viewer_app.error
    assert any("No valid tracks" in x.value for x in viewer_app.info)
