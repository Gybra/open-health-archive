import importlib
from dataclasses import replace

import pandas as pd
import pytest
from fixture_archive import fixture_row
from viewer_archive import write_viewer_archive

from healthviz.archive.reader import load_archive
from healthviz.settings import Settings, SettingsError


def resolve(metric, rows, tmp_path, settings=None):
    settings = settings or Settings()
    assert importlib.util.find_spec("healthviz.analysis"), "source analysis is missing"
    mod = importlib.import_module("healthviz.analysis.sources")
    tables = load_archive(write_viewer_archive(tmp_path, **{metric: rows}))
    return mod.resolve_rows(metric, tables[metric], tables["devices"], settings)


def step(
    device="fixture-watch",
    count="100",
    start="2026-01-01T00:00:00Z",
    end="2026-01-01T00:01:00Z",
    offset="+01:00",
    ingest="xiaomi_export",
    key="a",
):
    return fixture_row(
        "steps",
        start_utc=start,
        end_utc=end,
        utc_offset=offset,
        count=count,
        device_id=device,
        record_id=key,
        ingest=ingest,
    )


def test_watch_wins_hour_without_phone_hole_fill(tmp_path):
    selected, audit = resolve(
        "steps",
        [
            step(),
            step(
                "fixture-phone",
                "60",
                start="2026-01-01T00:30:00Z",
                end="2026-01-01T00:31:00Z",
                key="b",
            ),
        ],
        tmp_path,
    )
    assert selected["count"].sum() == 100
    assert len(audit) == 2
    assert audit["selected"].sum() == 1


def test_interval_split_conserves_value(tmp_path):
    selected, _ = resolve(
        "steps",
        [step(count="120", start="2026-01-01T22:59:00Z", end="2026-01-01T23:01:00Z")],
        tmp_path,
    )
    assert selected["count"].tolist() == [60, 60]
    assert selected["date_local"].astype(str).tolist() == ["2026-01-01", "2026-01-02"]
    assert selected["allocation_estimated"].all()


def test_dst_fold_travel_and_conflicting_hour_windows(tmp_path):
    rows = [
        step(start="2026-10-25T00:00:00Z", end="2026-10-25T00:01:00Z", offset="+02:00"),
        step(start="2026-10-25T01:00:00Z", end="2026-10-25T01:01:00Z", offset="+01:00", key="b"),
    ]
    selected, _ = resolve("steps", rows, tmp_path / "fold")
    assert selected["hour_start_utc"].nunique() == 2
    rows = [
        step(
            start="2026-01-01T00:50:00Z",
            end="2026-01-01T00:51:00Z",
            offset="+00:30",
            device="fixture-phone",
        ),
        step(start="2026-01-01T01:50:00Z", end="2026-01-01T01:51:00Z", key="b"),
    ]
    selected, _ = resolve("steps", rows, tmp_path / "conflict")
    assert selected["count"].sum() == 200
    assert selected["end_utc"].iloc[0] <= selected["start_utc"].iloc[1]


def test_explicit_alias_preserves_provenance(tmp_path):
    rows = [step(device="fixture-watch-2")]
    selected, _ = resolve(
        "steps",
        rows,
        tmp_path,
        replace(Settings(), device_aliases={"fixture-watch-2": "fixture-watch"}),
    )
    assert selected.iloc[0]["device_id"] == "fixture-watch-2"
    assert selected.iloc[0]["physical_device_id"] == "fixture-watch"


def test_override_priority_and_stable_tie(tmp_path):
    rows = [step(), step("fixture-phone", "60", key="b")]
    settings = Settings(priority={"steps": ["fixture-phone"]})
    first, _ = resolve("steps", rows, tmp_path / "a", settings)
    second, _ = resolve("steps", list(reversed(rows)), tmp_path / "b", settings)
    pd.testing.assert_frame_equal(first.reset_index(drop=True), second.reset_index(drop=True))
    assert first["count"].sum() == 60


def test_calorie_kinds_resolve_independently(tmp_path):
    rows = [
        fixture_row(
            "calories",
            start_utc="2026-01-01T00:00:00Z",
            end_utc="2026-01-01T00:01:00Z",
            utc_offset="+01:00",
            kind=kind,
            kcal=value,
            record_id=kind,
        )
        for kind, value in [("active", "10"), ("total", "20")]
    ]
    selected, _ = resolve("calories", rows, tmp_path)
    assert dict(zip(selected["kind"], selected["kcal"], strict=True)) == {"active": 10, "total": 20}


def test_same_source_overlap_is_ambiguous(tmp_path):
    selected, _ = resolve("steps", [step(), step(key="b")], tmp_path)
    assert (selected["quality"] == "ambiguous").all()


def test_cross_source_session_overlap(tmp_path):
    rows = [
        fixture_row(
            "workouts",
            workout_id=key,
            type="walking",
            start_utc=start,
            end_utc=end,
            utc_offset="+01:00",
            device_id=device,
            record_id=key,
        )
        for key, device, start, end in [
            ("a", "fixture-watch", "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"),
            ("b", "fixture-phone", "2026-01-01T00:30:00Z", "2026-01-01T01:30:00Z"),
            ("c", "fixture-phone", "2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"),
        ]
    ]
    selected, _ = resolve("workouts", rows, tmp_path)
    assert selected["workout_id"].tolist() == ["a", "c"]


def test_alias_unknown_device_rejected(tmp_path):
    with pytest.raises(SettingsError):
        resolve(
            "steps", [step()], tmp_path, Settings(device_aliases={"unregistered": "fixture-watch"})
        )
