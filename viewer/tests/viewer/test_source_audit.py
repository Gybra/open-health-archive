from fixture_archive import fixture_row
from viewer_archive import write_viewer_archive

from healthviz.analysis.sources import resolve_rows
from healthviz.archive.reader import load_archive
from healthviz.settings import Settings


def test_audit_reports_actual_hour_winner(tmp_path):
    rows = [
        fixture_row(
            "steps",
            start_utc=start,
            end_utc=end,
            utc_offset="+01:00",
            count="100",
            device_id=device,
            record_id=key,
        )
        for key, device, start, end in [
            ("watch", "fixture-watch", "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"),
            ("lost-phone", "fixture-phone", "2026-01-01T00:30:00Z", "2026-01-01T00:31:00Z"),
            ("won-phone", "fixture-phone", "2026-01-01T01:30:00Z", "2026-01-01T01:31:00Z"),
        ]
    ]
    tables = load_archive(write_viewer_archive(tmp_path, steps=rows))
    _, audit = resolve_rows("steps", tables["steps"], tables["devices"], Settings())
    assert audit.set_index("record_id").loc["lost-phone", "winner_id"] == "fixture-watch"
    assert audit.set_index("record_id").loc["won-phone", "winner_id"] == "fixture-phone"
