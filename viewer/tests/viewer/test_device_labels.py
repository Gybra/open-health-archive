import pandas as pd

from healthviz.analysis.devices import device_label, device_sources, suggest_duplicates
from healthviz.settings import Settings

DEVICES = pd.DataFrame(
    {
        "device_id": ["export-watch", "hc-watch", "hc-phone"],
        "vendor": ["Fictional", "Fictional", None],
        "model": ["Band 9", None, None],
        "kind": ["watch", "watch", "phone"],
    }
)


def steps(rows):
    """rows: (device_id, ingest, source_app, day of month, count)."""
    return pd.DataFrame(
        [
            {
                "start_utc": pd.Timestamp(f"2026-03-{day:02d} 10:00", tz="UTC"),
                "end_utc": pd.Timestamp(f"2026-03-{day:02d} 11:00", tz="UTC"),
                "utc_offset": "+01:00",
                "count": count,
                "device_id": device,
                "ingest": ingest,
                "source_app": app,
                "record_id": f"{device}-{day}",
            }
            for device, ingest, app, day, count in rows
        ]
    )


def tables(rows):
    return {"devices": DEVICES, "steps": steps(rows)}


def same_watch(days=4, other=1.05):
    return [
        row
        for day in range(1, days + 1)
        for row in [
            ("export-watch", "xiaomi_export", "com.mi.health", day, 8000),
            ("hc-watch", "health_connect", "com.xiaomi.wearable", day, round(8000 * other)),
            ("hc-phone", "health_connect", "com.android.healthconnect.phone.ab12", day, 8100),
        ]
    ]


def test_labels_name_app_model_and_ingest():
    found = tables(same_watch())
    sources = device_sources(found)
    assert device_label("export-watch", DEVICES, sources) == "Mi Fitness · Band 9 (Xiaomi export)"
    assert device_label("hc-watch", DEVICES, sources) == "Mi Fitness · Watch (Health Connect)"
    assert device_label("hc-phone", DEVICES, sources) == "Phone (Health Connect)"
    assert device_label("missing", DEVICES, sources) == "missing"


def test_matching_daily_steps_from_two_ingests_are_suggested():
    # The phone has matching counts too, but a phone is not the same device as a watch.
    assert suggest_duplicates(tables(same_watch()), Settings()) == [("export-watch", "hc-watch")]


def test_associated_or_dismissed_pairs_are_not_suggested():
    found = tables(same_watch())
    associated = Settings(device_aliases={"hc-watch": "export-watch"})
    dismissed = Settings(not_same_devices=[["export-watch", "hc-watch"]])
    assert suggest_duplicates(found, associated) == []
    assert suggest_duplicates(found, dismissed) == []


def test_different_step_counts_are_not_suggested():
    assert suggest_duplicates(tables(same_watch(other=1.3)), Settings()) == []
    assert suggest_duplicates(tables(same_watch(days=2)), Settings()) == []
