from zoneinfo import ZoneInfo

from xiaomi_export import MANUAL_SID, fitness_row, load

from healthviz.xiaomi.offsets import OffsetResolver
from healthviz.xiaomi.samples import map_samples


def mapped(root, rows):
    export, devices = load(root, fitness=rows)
    return map_samples(
        export, devices, OffsetResolver(ZoneInfo("Europe/Rome"), [])
    ), export.warnings


def test_hr_and_provenance(tmp_path):
    out, warnings = mapped(tmp_path, [fitness_row("heart_rate", 1767225600, {"bpm": 61})])
    assert warnings == []
    assert out["heart_rate"] == [
        {
            "time_utc": "2026-01-01T00:00:00Z",
            "utc_offset": "+01:00",
            "bpm": "61",
            "device_id": "xiaomi-watch-bdc5d8a48c238979",
            "ingest": "xiaomi_export",
            "source_app": "com.mi.health",
            "record_id": "xiaomi-watch-bdc5d8a48c238979:heart_rate:1767225600",
        }
    ]


def test_steps_without_double_counting(tmp_path):
    out, _ = mapped(
        tmp_path,
        [
            fitness_row("steps", 1767225600, {"steps": 80, "distance": 55, "calories": 3}),
            fitness_row("steps", 1767225660, {"steps": 20, "distance": 0, "calories": 1}),
            fitness_row("calories", 1767225600, {"calories": 4}),
        ],
    )
    assert len(out["steps"]) == 2 and len(out["distance"]) == 1
    assert out["steps"][0]["end_utc"] == "2026-01-01T00:01:00Z"
    assert out["distance"][0]["distance_m"] == "55"
    assert len(out["calories"]) == 1 and out["calories"][0]["kind"] == "active"
    assert out["calories"][0]["kcal"] == "4"


def test_vitals_and_manual_weight(tmp_path):
    out, _ = mapped(
        tmp_path,
        [
            fitness_row("resting_heart_rate", 1767225600, {"date_time": 1767225600, "bpm": 55}),
            fitness_row("spo2", 1767225600, {"time": 1767225600, "spo2": 98}),
            fitness_row("single_spo2", 1767225600, {"time": 1767225600, "spo2": 97}),
            fitness_row("weight", 1767225600, {"time": 1767225600, "weight": 65.0}, sid=MANUAL_SID),
        ],
    )
    assert out["resting_heart_rate"][0]["date_local"] == "2026-01-01"
    assert out["resting_heart_rate"][0]["computed_by"] == "vendor"
    assert len({r["record_id"] for r in out["spo2"]}) == 2
    assert out["weight"][0]["kg"] == "65.0"
    assert out["weight"][0]["device_id"] == "xiaomi-manual-fa88d374b9cf5e05"


def test_dropped_invalid_and_unknown_no_values_logged(tmp_path):
    out, warnings = mapped(
        tmp_path,
        [
            fitness_row("intensity", 1767225600, {"time": 1767225600}),
            fitness_row("PRIVATE_KEY", 1767225600, {"PRIVATE": 123}),
            fitness_row("heart_rate", 1767225600, {"bpm": float("nan")}),
        ],
    )
    assert all(not rows for rows in out.values())
    assert len(warnings) == 2 and "PRIVATE" not in str(warnings)
