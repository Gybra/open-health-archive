from xiaomi_export import fitness_row, load, sport_row

from healthviz.xiaomi.sleep import map_sleep
from healthviz.xiaomi.workouts import map_workouts


def sleep_value(**changes):
    return {
        "bedtime": 1767222000,
        "wake_up_time": 1767250800,
        "timezone": 4,
        "sleep_deep_duration": 60,
        "sleep_light_duration": 400,
        "sleep_awake_duration": 0,
        **changes,
    }


def test_sleep_stages_and_unknown(tmp_path):
    items = [
        dict(start_time=1767222000, end_time=1767225600, state=3),
        dict(start_time=1767225600, end_time=1767229200, state=2),
        dict(start_time=1767229200, end_time=1767229500, state=4),
    ]
    out = map_sleep(
        *load(tmp_path, fitness=[fitness_row("sleep", 1767250800, sleep_value(items=items))])
    )
    s = out["sleep_sessions"][0]
    assert (s["start_utc"], s["end_utc"], s["utc_offset"]) == (
        "2025-12-31T23:00:00Z",
        "2026-01-01T07:00:00Z",
        "+01:00",
    )
    assert (s["has_stages"], s["deep_min"], s["rem_min"], s["computed_by"]) == (
        "true",
        "",
        "",
        "device",
    )
    assert [x["stage"] for x in out["sleep_stages"]] == ["light", "deep", "unknown"]
    assert out["sleep_stages"][2]["source_type"] == "4"


def test_no_stages_and_incomplete_flag(tmp_path):
    out = map_sleep(
        *load(tmp_path, fitness=[fitness_row("sleep", 1767250800, sleep_value(is_uncomplete=True))])
    )
    s = out["sleep_sessions"][0]
    assert (s["has_stages"], s["deep_min"], s["rem_min"]) == ("false", "60", "")
    assert (s["is_complete"], s["computed_by"]) == ("false", "vendor")


def test_missing_and_reversed_sleep_skipped(tmp_path):
    export, devices = load(
        tmp_path,
        fitness=[
            fitness_row("sleep", 1, {"bedtime": 123}),
            fitness_row("sleep", 2, sleep_value(bedtime=1767260800)),
        ],
    )
    assert map_sleep(export, devices)["sleep_sessions"] == []
    assert len(export.warnings) == 2


def workout_value(**changes):
    return {
        "start_time": 1767258000,
        "end_time": 1767261600,
        "timezone": 4,
        "duration": 3600,
        "distance": 4200,
        "steps": 5600,
        "calories": 210,
        "total_cal": 260,
        "avg_hrm": 112,
        "max_hrm": 140,
        "rise_height": 0.0,
        "fall_height": 12.34,
        **changes,
    }


def test_workout_mapping(tmp_path):
    w = map_workouts(
        *load(tmp_path, sport=[sport_row("outdoor_walking", 1767258000, workout_value())])
    )[0]
    assert w["workout_id"] == "xiaomi-d1f87b9c1d1f3dbe"
    assert (w["type"], w["source_type"]) == ("walking", "outdoor_walking")
    assert (w["active_kcal"], w["total_kcal"], w["distance_m"]) == ("210", "260", "4200")
    assert (w["ascent_m"], w["descent_m"], w["ascent_computed_by"]) == ("0.0", "12.3", "vendor")
    assert w["track_file"] == ""


def test_unknown_type_is_preserved_but_not_logged(tmp_path):
    export, devices = load(tmp_path, sport=[sport_row("PRIVATE_123", 1767258000, workout_value())])
    w = map_workouts(export, devices)[0]
    assert (w["type"], w["source_type"]) == ("other_workout", "PRIVATE_123")
    assert "PRIVATE" not in str(export.warnings)


def test_zero_vitals_empty(tmp_path):
    v = workout_value()
    v.update(distance=0, avg_hrm=0)
    w = map_workouts(*load(tmp_path, sport=[sport_row("cross_fit", 1767258000, v)]))[0]
    assert w["distance_m"] == "" and w["avg_hr"] == ""
