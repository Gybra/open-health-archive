import csv
import io
from unittest.mock import patch

import pandas as pd
from dashboard_nav import open_page
from fixture_archive import FIXTURE_TABLES
from viewer_archive import write_viewer_archive

from healthviz.analysis.sources import source_rank
from healthviz.dashboard.charts import summary_table
from healthviz.settings import Settings


def test_archive_text_cannot_render_remote_images(viewer_app, tmp_path):
    marker = "![PRIVATE-SENTINEL](https://example.invalid/image.png)"
    row = {**FIXTURE_TABLES["workouts"][-1], "type": marker, "track_file": ""}
    write_viewer_archive(tmp_path / "archive", workouts=[row])
    open_page(viewer_app, "Activity")
    assert not viewer_app.error
    assert any(marker in text.value for text in viewer_app.text)
    assert not any(marker in text.value for text in viewer_app.markdown)


def test_csv_whitespace_cannot_bypass_formula_escape():
    value = '\t=WEBSERVICE("https://example.invalid")'
    with patch("healthviz.dashboard.charts.st.download_button") as download:
        summary_table(pd.DataFrame({"type": [value]}), "Synthetic")
    rows = list(csv.DictReader(io.StringIO(download.call_args.args[1].decode())))
    assert rows[0]["type"] == "'" + value


def test_alias_does_not_turn_app_summary_into_watch():
    devices = pd.DataFrame(
        {"device_id": ["app", "watch", "phone"], "kind": ["app", "watch", "phone"]}
    )
    settings = Settings(device_aliases={"app": "watch"})
    app = source_rank("steps", ("app", "xiaomi_export", ""), devices, settings)
    phone = source_rank("steps", ("phone", "health_connect", ""), devices, settings)
    assert app > phone
