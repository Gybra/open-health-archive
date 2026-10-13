import threading


def test_heatmap_does_not_calculate_workout_pace(viewer_app):
    calls = []
    previous = threading.getprofile()

    def record(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "route_profile":
            calls.append(True)

    try:
        threading.setprofile(record)
        viewer_app.selectbox(key="page").select("Map").run()
    finally:
        threading.setprofile(previous)
    assert not viewer_app.error
    assert not calls, "density needs route continuity, not every point's rolling pace"


def test_heatmap_rerun_reuses_density(viewer_app):
    viewer_app.selectbox(key="page").select("Map").run()
    calls = []
    previous = threading.getprofile()

    def record(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "density_points":
            calls.append(True)

    try:
        threading.setprofile(record)
        viewer_app.run()
    finally:
        threading.setprofile(previous)
    assert not viewer_app.error
    assert not calls, "an unchanged map must not resample every track again"


def test_heatmap_filter_does_not_show_previous_geometry(viewer_app):
    viewer_app.selectbox(key="page").select("Map").run()
    types = next(control for control in viewer_app.multiselect if control.label == "Activity types")
    types.set_value([])
    viewer_app.run()
    assert not viewer_app.error
    assert any(item.value == "No valid tracks match these filters." for item in viewer_app.info)
