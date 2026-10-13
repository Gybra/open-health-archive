import importlib
from datetime import date

import pandas as pd
import pytest


@pytest.mark.parametrize("page", ["Overview", "Sleep", "Activity & calories", "Day", "Overlaps"])
def test_non_map_pages_render(viewer_app, page):
    viewer_app.selectbox(key="page").set_value(page).run()
    assert not viewer_app.exception
    assert not viewer_app.error


def test_filtered_exports_and_gaps():
    assert importlib.util.find_spec("healthviz.dashboard"), "charts are missing"
    charts = importlib.import_module("healthviz.dashboard.charts")
    frame = pd.DataFrame(
        {
            "date_local": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "steps": [100, 200, 300],
            "complete": [True, False, True],
            "steps_physical_device_id": ["a", "a", "b"],
            "steps_computed_by": ["device"] * 3,
        }
    )
    fig = charts.trend(frame, "steps", "Steps", "count")
    assert pd.isna(fig.data[0].y[1])
    assert fig.data[0].connectgaps is False
    assert len(fig.layout.shapes) == 1
