from xiaomi_export import aggregated_row, load

from healthviz.xiaomi.fallback import map_vendor_daily


def test_raw_day_suppresses_fallback(tmp_path):
    e, devices = load(
        tmp_path,
        aggregated=[
            aggregated_row("daily_report", "steps", 1767225600, {"steps": 4000, "distance": 2800}),
            aggregated_row("daily_report", "steps", 1767312000, {"steps": 5000, "distance": 3500}),
        ],
    )
    raw = {"steps": [{"start_utc": "2026-01-01T12:00:00Z", "utc_offset": "+01:00"}]}
    out = map_vendor_daily(e, devices, raw)
    assert {(r["date_local"], r["metric"], r["value"]) for r in out} == {
        ("2026-01-02", "steps", "5000"),
        ("2026-01-02", "distance", "3500"),
    }
    assert all(r["computed_by"] == "vendor" for r in out)


def test_sleep_uses_wake_day_and_ignores_other_tags(tmp_path):
    e, devices = load(
        tmp_path,
        aggregated=[
            aggregated_row("daily_report", "sleep", 1767225600, {"total_duration": 480}),
            aggregated_row("daily_mark", "steps", 1767225600, {"steps": 100}),
            aggregated_row("daily_report", "calories", 1767225600, {"calories": 0}),
        ],
    )
    raw = {"sleep_sessions": [{"end_utc": "2026-01-01T07:00:00Z", "utc_offset": "+01:00"}]}
    assert map_vendor_daily(e, devices, raw) == []
