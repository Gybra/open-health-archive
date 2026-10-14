from datetime import date

import pytest
from fixture_archive import fixture_row

from healthviz.analysis.apps import select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.reader import load_archive
from healthviz.archive.schema import TABLES
from healthviz.archive.writer import write_archive
from healthviz.settings import Settings

# Health Connect's export carries the same watch under its own ingest and a pseudonymous device.
XIAOMI = ("xiaomi_export", "xm-watch", "com.mi.health")
HEALTH_CONNECT = ("health_connect", "hc-0011223344556677", "com.xiaomi.wearable")
SOURCES = (XIAOMI, HEALTH_CONNECT)
PHONE = ("health_connect", "hc-8899aabbccddeeff", "com.android.healthconnect.phone.0123abcd")


def overlapping_archive(root):
    tables = {name: [] for name in TABLES if name != "devices"}
    for ingest, device, app in SOURCES:
        provenance = dict(device_id=device, ingest=ingest, source_app=app)
        for hour in (10, 11):
            tables["steps"].append(
                fixture_row(
                    "steps",
                    start_utc=f"2026-03-02T{hour}:00:00Z",
                    end_utc=f"2026-03-02T{hour}:30:00Z",
                    utc_offset="+01:00",
                    count="100",
                    record_id=f"{ingest}-steps-{hour}",
                    **provenance,
                )
            )
        tables["sleep_sessions"].append(
            fixture_row(
                "sleep_sessions",
                session_id=f"{ingest}-night",
                start_utc="2026-03-01T23:00:00Z",
                end_utc="2026-03-02T06:00:00Z",
                utc_offset="+01:00",
                has_stages="false",
                deep_min="60",
                light_min="240",
                rem_min="60",
                awake_min="20",
                computed_by="vendor",
                record_id=f"{ingest}-night",
                **provenance,
            )
        )
        tables["workouts"].append(
            fixture_row(
                "workouts",
                workout_id=f"{ingest}-walk",
                type="walking",
                start_utc="2026-03-02T16:00:00Z",
                end_utc="2026-03-02T16:30:00Z",
                utc_offset="+01:00",
                record_id=f"{ingest}-walk",
                **provenance,
            )
        )
    # Health Connect's own step counter on the phone counts part of the same walk.
    tables["steps"].append(
        fixture_row(
            "steps",
            start_utc="2026-03-02T10:00:00Z",
            end_utc="2026-03-02T10:30:00Z",
            utc_offset="+01:00",
            count="30",
            record_id="phone-steps",
            device_id=PHONE[1],
            ingest=PHONE[0],
            source_app=PHONE[2],
        )
    )
    devices = [
        dict(
            device_id=device,
            vendor="Fictional",
            model=model,
            kind=kind,
            first_seen_utc="",
            last_seen_utc="",
        )
        for device, model, kind in [
            (XIAOMI[1], "Watch", "watch"),
            (HEALTH_CONNECT[1], "Watch", "watch"),
            (PHONE[1], "Phone", "phone"),
        ]
    ]
    write_archive(root, tables, devices, {}, "synthetic overlap")
    return load_archive(root)


@pytest.mark.parametrize(
    "settings",
    [Settings(), Settings(device_aliases={HEALTH_CONNECT[1]: XIAOMI[1]})],
    ids=["separate devices", "same physical watch"],
)
@pytest.mark.parametrize("apps", [[], ["Mi Fitness"]], ids=["all apps", "Mi Fitness"])
def test_health_connect_overlap_is_not_double_counted(tmp_path, settings, apps):
    tables = select_apps(overlapping_archive(tmp_path / "archive"), apps)

    daily = daily_summary(tables, tables["devices"], settings).set_index("date_local")
    sleep, _ = resolve_rows("sleep_sessions", tables["sleep_sessions"], tables["devices"], settings)
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)

    assert daily.loc[date(2026, 3, 2), "steps"] == 200
    assert len(sleep) == 1
    assert len(workouts) == 1


def test_vendor_export_wins_over_health_connect_for_the_same_watch(tmp_path):
    tables = overlapping_archive(tmp_path / "archive")
    settings = Settings(device_aliases={HEALTH_CONNECT[1]: XIAOMI[1]})

    sleep, _ = resolve_rows("sleep_sessions", tables["sleep_sessions"], tables["devices"], settings)

    assert set(sleep.ingest) == {"xiaomi_export"}


def test_phone_alone_shows_only_its_own_steps(tmp_path):
    tables = select_apps(overlapping_archive(tmp_path / "archive"), ["Phone (Health Connect)"])

    daily = daily_summary(tables, tables["devices"], Settings()).set_index("date_local")

    assert daily.loc[date(2026, 3, 2), "steps"] == 30
