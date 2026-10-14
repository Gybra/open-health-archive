from benchmark_read_model import generate_archive

from healthviz.analysis.heart import max_hr, workout_heart_rate
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.reader import load_archive
from healthviz.settings import Settings

COLUMNS = ["time_utc", "bpm", "device_id", "ingest", "record_id"]


def test_workout_heart_rate_matches_full_resolution(tmp_path):
    # Two weeks with a phone and a second watch overlapping, DST and a +05:30 trip.
    generate_archive(tmp_path / "archive", sample_count=45_000)
    tables = load_archive(tmp_path / "archive")
    devices, settings = tables["devices"], Settings()
    full, _ = resolve_rows("heart_rate", tables["heart_rate"], devices, settings)
    workouts, _ = resolve_rows("workouts", tables["workouts"], devices, settings)
    part = workout_heart_rate(tables["heart_rate"], workouts, devices, settings)
    assert len(part) < len(full) / 5
    competing = 0
    for workout in workouts.itertuples():

        def inside(hr, workout=workout):
            rows = hr.loc[(hr.time_utc >= workout.start_utc) & (hr.time_utc < workout.end_utc)]
            return rows[COLUMNS].sort_values(["time_utc", "record_id"]).reset_index(drop=True)

        assert inside(part).equals(inside(full)), workout.record_id
        raw = tables["heart_rate"]
        competing += (
            raw.loc[
                (raw.time_utc >= workout.start_utc) & (raw.time_utc < workout.end_utc)
            ].device_id.nunique()
            > 1
        )
        assert max_hr(settings, part, workouts, workout.date_local) == max_hr(
            settings, full, workouts, workout.date_local
        )
    assert competing


def test_a_source_winning_the_hour_after_the_workout_still_counts(tmp_path):
    import pandas as pd

    generate_archive(tmp_path / "archive", sample_count=6_000)
    tables = load_archive(tmp_path / "archive")
    devices = tables["devices"]
    settings = Settings(priority={"heart_rate": ["fixture-watch-2", "fixture-watch"]})
    workouts, _ = resolve_rows("workouts", tables["workouts"], devices, settings)
    workout = workouts.iloc[0]
    raw = tables["heart_rate"]
    # The preferred watch reports only after the workout, inside the same local hour.
    template = raw.loc[raw.device_id == "fixture-watch"].iloc[[0]]
    later = pd.concat(
        template.assign(
            time_utc=workout.end_utc + pd.Timedelta(minutes=minute),
            device_id="fixture-watch-2",
            record_id=f"late-{minute}",
        )
        for minute in (10, 20)
    )
    rows = pd.concat([raw.loc[raw.device_id != "fixture-watch-2"], later], ignore_index=True)
    full, _ = resolve_rows("heart_rate", rows, devices, settings)
    part = workout_heart_rate(rows, workouts, devices, settings)

    def inside(hr):
        hr = hr.loc[(hr.time_utc >= workout.start_utc) & (hr.time_utc < workout.end_utc)]
        return hr[COLUMNS].sort_values(["time_utc", "record_id"]).reset_index(drop=True)

    assert inside(full).empty
    assert inside(part).equals(inside(full))


def reference_max_hr(hr, workouts, as_of):
    """The boolean-filter version max_hr replaced; the year window starts on the same date."""
    import calendar
    from datetime import timedelta

    import pandas as pd

    start = as_of.replace(
        year=as_of.year - 1, day=min(as_of.day, calendar.monthrange(as_of.year - 1, as_of.month)[1])
    )
    lower, upper = pd.Timestamp(start, tz="UTC"), pd.Timestamp(as_of + timedelta(days=1), tz="UTC")
    peaks = []
    for workout in workouts.itertuples():
        samples = hr.loc[
            (hr.time_utc >= max(lower, workout.start_utc))
            & (hr.time_utc < min(upper, workout.end_utc))
        ].sort_values("time_utc")
        bpm = samples.bpm
        confirmed = (
            (bpm - bpm.shift()).abs().le(10)
            & (bpm - bpm.shift(-1)).abs().le(10)
            & samples.time_utc.diff().dt.total_seconds().le(120)
            & (samples.time_utc.shift(-1) - samples.time_utc).dt.total_seconds().le(120)
        )
        if confirmed.any():
            peaks.append(float(bpm.loc[confirmed].max()))
    return (max(peaks), "observed") if peaks else (None, "unavailable")


def test_max_hr_matches_the_boolean_filter(tmp_path):
    generate_archive(tmp_path / "archive", sample_count=45_000)
    tables = load_archive(tmp_path / "archive")
    settings = Settings()
    hr, _ = resolve_rows("heart_rate", tables["heart_rate"], tables["devices"], settings)
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    for day in sorted(set(workouts.date_local)):
        assert max_hr(settings, hr, workouts, day) == reference_max_hr(hr, workouts, day)
