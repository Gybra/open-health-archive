"""Readable device names and suggestions of one physical device seen through two ingests."""

from itertools import combinations

import pandas as pd

from healthviz.analysis.apps import app_label
from healthviz.analysis.sources import annotate
from healthviz.settings import Settings

INGESTS = {"xiaomi_export": "Xiaomi export", "health_connect": "Health Connect"}
MATCHING_DAYS = 3
TOLERANCE = 0.1


def device_sources(tables: dict[str, pd.DataFrame]) -> dict[str, tuple[str, str]]:
    """device_id → its most frequent (source_app, ingest)."""
    parts = [
        frame[["device_id", "source_app", "ingest"]]
        for name, frame in tables.items()
        if name != "devices" and {"device_id", "source_app", "ingest"}.issubset(frame)
    ]
    if not parts:
        return {}
    rows = pd.concat(parts).fillna({"source_app": ""})
    counts = rows.value_counts().reset_index().drop_duplicates("device_id")
    return {r.device_id: (r.source_app, r.ingest) for r in counts.itertuples()}


def device_label(device_id: str, devices: pd.DataFrame, sources) -> str:
    row = devices.loc[devices.device_id == device_id]
    if row.empty:
        return device_id
    row = row.iloc[0]
    app, ingest = sources.get(device_id, ("", ""))
    app = app_label(app)
    name = row.model if isinstance(row.model, str) and row.model else str(row.kind).title()
    text = app if name in app else f"{app} · {name}"
    origin = INGESTS.get(ingest, ingest)
    return text if not origin or origin in text else f"{text} ({origin})"


def suggest_duplicates(
    tables: dict[str, pd.DataFrame], settings: Settings
) -> list[tuple[str, str]]:
    """Same-kind devices from different ingests whose daily steps agree on several days.

    Only a suggestion: the owner decides; associated or dismissed pairs never return.
    """
    rows = tables["steps"]
    if rows.empty:
        return []
    rows = annotate(rows, "steps", settings)
    totals = rows.groupby(["device_id", "date_local"])["count"].sum().unstack()
    ingests = rows.groupby("device_id").ingest.first()
    physical = rows.groupby("device_id").physical_device_id.first()
    kinds = dict(zip(tables["devices"].device_id, tables["devices"].kind, strict=True))
    dismissed = {tuple(pair) for pair in settings.not_same_devices}
    found = []
    for a, b in combinations(sorted(totals.index), 2):
        if (
            ingests[a] == ingests[b]
            or physical[a] == physical[b]
            or kinds.get(a) != kinds.get(b)
            or (a, b) in dismissed
        ):
            continue
        both = totals.loc[[a, b]].dropna(axis=1)
        close = (both.loc[a] - both.loc[b]).abs() <= TOLERANCE * both.max()
        if close.sum() >= MATCHING_DAYS:
            found.append((a, b))
    return found
