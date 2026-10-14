"""Readable app names for source_app values and the dashboard's app filter."""

import pandas as pd

LABELS = {
    # The Xiaomi export and Mi Fitness via Health Connect are the same app and watch.
    "com.mi.health": "Mi Fitness",
    "com.xiaomi.wearable": "Mi Fitness",
    "com.hihonor.health": "Honor Health",
    "com.google.android.apps.fitness": "Google Fit",
}
PREFIXES = {"com.android.healthconnect.phone": "Phone (Health Connect)"}
UNKNOWN = "Unknown app"


def app_label(source_app: str | None) -> str:
    if not source_app or pd.isna(source_app):
        return UNKNOWN
    if source_app in LABELS:
        return LABELS[source_app]
    for prefix, label in PREFIXES.items():
        if source_app.startswith(prefix):
            return label
    return source_app


def labels(frame: pd.DataFrame) -> pd.Series:
    values = frame.source_app.fillna("")
    return values.map({value: app_label(value) for value in values.unique()})


def app_choices(tables: dict[str, pd.DataFrame]) -> list[str]:
    found = set()
    for name, frame in tables.items():
        if name != "devices" and "source_app" in frame and not frame.empty:
            found.update(labels(frame).unique())
    return sorted(found)


def select_apps(tables: dict[str, pd.DataFrame], apps: list[str]) -> dict[str, pd.DataFrame]:
    """Rows from the chosen apps; no choice, or none present, means every app."""
    chosen = set(apps) & set(app_choices(tables))
    if not chosen:
        return tables
    return {
        name: frame
        if name == "devices" or "source_app" not in frame
        else frame.loc[labels(frame).isin(chosen)]
        for name, frame in tables.items()
    }
