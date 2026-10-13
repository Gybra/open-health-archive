import importlib

import pandas as pd
from viewer_archive import write_viewer_archive

from healthviz.analysis.sources import resolve_rows
from healthviz.archive.reader import load_archive
from healthviz.settings import Settings


def nights(root):
    assert importlib.util.find_spec("healthviz.analysis.sleep"), "sleep analysis is missing"
    tables = load_archive(root)
    sessions, _ = resolve_rows(
        "sleep_sessions", tables["sleep_sessions"], tables["devices"], Settings()
    )
    mod = importlib.import_module("healthviz.analysis.sleep")
    return mod.sleep_summary(sessions, tables["sleep_stages"]).set_index("session_id")


def test_sleep_wake_day_main_nap_and_incomplete(tmp_path):
    result = nights(write_viewer_archive(tmp_path))
    from datetime import date

    assert result.loc["main-complete", "date_local"] == date(2026, 1, 3)
    assert result.loc["main-complete", "main"]
    assert not result.loc["nap", "main"]
    assert result.loc["main-complete", "sleep_min"] == 480
    assert not result.loc["incomplete", "eligible"]
    assert result.loc["old-night", "completeness"] == "unknown"


def test_stages_vendor_totals_and_unknown_rem(tmp_path):
    result = nights(write_viewer_archive(tmp_path))
    assert result.loc["night", "sleep_min"] == 60
    assert result.loc["old-night", "sleep_min"] == 60
    assert pd.isna(result.loc["night", "rem_min"])
    assert result.loc["night", "light_share"] == 1
    assert result.loc["night", "uncovered_min"] == 0
