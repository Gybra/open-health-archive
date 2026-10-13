import heapq

import pandas as pd

from healthviz.archive.values import parse_offset
from healthviz.settings import Settings

SOURCE = ["device_id", "ingest", "source_app"]
VALUES = {"steps": "count", "distance": "distance_m", "calories": "kcal"}
EXTRA = ["physical_device_id", "date_local", "hour_start_utc", "allocation_estimated", "quality"]


def source_rank(metric, source, devices, settings):
    device, ingest, app = source
    physical = settings.device_aliases.get(device, device)
    order = [settings.device_aliases.get(v, v) for v in settings.priority.get(metric, [])]
    kinds = dict(zip(devices.device_id, devices.kind, strict=True))
    kind_order = ["watch", "phone", "manual", "app", "other"]
    explicit = order.index(physical) if physical in order else len(order)
    ingest_order = settings.ingest_priority.get(physical, [])
    ingest_rank = (
        ingest_order.index(ingest)
        if ingest in ingest_order
        else len(ingest_order)
        + (0 if ingest.endswith("_export") else 1 if ingest == "health_connect" else 2)
    )
    return (
        explicit,
        kind_order.index(kinds.get(device, "other")),
        ingest_rank,
        ingest,
        device,
        app,
    )


def annotate(rows, metric, settings):
    frame = rows.copy().reset_index(drop=True)
    frame["source_app"] = frame["source_app"].fillna("")
    frame["physical_device_id"] = frame.device_id.map(settings.device_aliases).fillna(
        frame.device_id
    )
    frame["allocation_estimated"] = False
    frame["quality"] = "observed"
    frame["_row"] = frame.index
    stamp = (
        "end_utc"
        if metric == "sleep_sessions"
        else "time_utc"
        if "time_utc" in frame
        else "start_utc"
    )
    if "utc_offset" in frame:
        offsets = frame.utc_offset.map(
            {v: pd.Timedelta(minutes=parse_offset(v)) for v in frame.utc_offset.unique()}
        )
        local = frame[stamp] + offsets
        frame["date_local"] = local.dt.date
        frame["hour_start_utc"] = local.dt.floor("h") - offsets
    else:
        frame["hour_start_utc"] = pd.NaT
    if "start_utc" in frame:
        for _, group in frame.groupby(
            [*SOURCE, "kind"] if metric == "calories" else SOURCE, dropna=False
        ):
            group = group.sort_values("start_utc")
            bad = group.start_utc < group.end_utc.cummax().shift()
            frame.loc[group.index[bad | bad.shift(-1, fill_value=False)], "quality"] = "ambiguous"
    return frame


def split_intervals(frame, boundaries):
    output = []
    remove = []
    crosses = boundaries.searchsorted(frame.end_utc, side="left") > boundaries.searchsorted(
        frame.start_utc, side="right"
    )
    for index, row in frame.loc[crosses].iterrows():
        left = boundaries.searchsorted(row.start_utc, side="right")
        right = boundaries.searchsorted(row.end_utc, side="left")
        if right <= left:
            continue
        remove.append(index)
        cuts = [row.start_utc, *boundaries[left:right], row.end_utc]
        for start, end in zip(cuts[:-1], cuts[1:], strict=True):
            output.append(
                {**row.to_dict(), "start_utc": start, "end_utc": end, "allocation_estimated": True}
            )
    return (
        pd.concat([frame.drop(index=remove), pd.DataFrame(output)], ignore_index=True)
        if output
        else frame
    )


def winning_windows(candidates, metric, devices, settings):
    events = {}
    ranks = {}
    for row in candidates.itertuples(index=False):
        key = row.candidate
        ranks[key] = source_rank(
            metric, (row.device_id, row.ingest, row.source_app), devices, settings
        )
        events.setdefault(row.hour_start_utc, []).append((1, key))
        events.setdefault(row.hour_start_utc + pd.Timedelta(hours=1), []).append((-1, key))
    active, heap, result = set(), [], []
    times = sorted(events)
    for position, time in enumerate(times[:-1]):
        for action, key in events[time]:
            if action == -1:
                active.discard(key)
            else:
                active.add(key)
                heapq.heappush(heap, (ranks[key], key))
        while heap and heap[0][1] not in active:
            heapq.heappop(heap)
        if heap:
            result.append(
                {"window_start": time, "window_end": times[position + 1], "winner": heap[0][1]}
            )
    return pd.DataFrame(result)


def hourly(frame, metric, devices, settings):
    interval = metric in VALUES
    if interval:
        frame["_duration"] = (frame.end_utc - frame.start_utc).dt.total_seconds()
        # Most intervals fit one hour; split only records crossing a known boundary.
        boundaries = []
        for row in frame.loc[
            frame.end_utc > frame.hour_start_utc + pd.Timedelta(hours=1)
        ].itertuples():
            boundaries.extend(
                pd.date_range(row.hour_start_utc + pd.Timedelta(hours=1), row.end_utc, freq="h")
            )
        if boundaries:
            frame = split_intervals(frame, pd.DatetimeIndex(sorted(set(boundaries))))
        offset = frame.utc_offset.map(
            {v: pd.Timedelta(minutes=parse_offset(v)) for v in frame.utc_offset.unique()}
        )
        local = frame.start_utc + offset
        frame["hour_start_utc"] = local.dt.floor("h") - offset
        frame["date_local"] = local.dt.date
    keys = ["hour_start_utc", *SOURCE]
    candidates = frame[keys].drop_duplicates().reset_index(drop=True)
    candidates["candidate"] = candidates.index
    frame = frame.merge(candidates, on=keys, validate="many_to_one")
    windows = winning_windows(candidates, metric, devices, settings)
    if interval:
        frame = split_intervals(frame, pd.DatetimeIndex(windows.window_start))
    stamp = "start_utc" if interval else "time_utc"
    joined = pd.merge_asof(
        frame.sort_values(stamp),
        windows.sort_values("window_start"),
        left_on=stamp,
        right_on="window_start",
    )
    keep = (joined.candidate == joined.winner) & (joined[stamp] < joined.window_end)
    selected = joined.loc[keep].copy()
    if interval:
        col = VALUES[metric]
        selected[col] = (
            selected[col].astype("Float64")
            * (selected.end_utc - selected.start_utc).dt.total_seconds()
            / selected["_duration"]
        )
    joined["winner_id"] = joined.winner.map(candidates.set_index("candidate").device_id).map(
        lambda v: settings.device_aliases.get(v, v)
    )
    return selected, joined[["_row", "winner_id"]]


def sessions(frame, metric, devices, settings):
    records = sorted(
        frame.to_dict("records"),
        key=lambda r: (
            source_rank(metric, tuple(r[c] for c in SOURCE), devices, settings),
            r["start_utc"],
            r["record_id"],
        ),
    )
    accepted = []
    for row in records:
        source = tuple(row[c] for c in SOURCE)
        if not any(
            tuple(other[c] for c in SOURCE) != source
            and row["start_utc"] < other["end_utc"]
            and other["start_utc"] < row["end_utc"]
            for other in accepted
        ):
            accepted.append(row)
    return pd.DataFrame(accepted, columns=frame.columns)


def date_values(frame, metric, devices, settings):
    chosen = []
    for _, group in frame.groupby("date_local", sort=True):
        source = min(
            (tuple(r) for r in group[SOURCE].drop_duplicates().itertuples(index=False, name=None)),
            key=lambda s: source_rank(metric, s, devices, settings),
        )
        matches = group.loc[(group[SOURCE] == source).all(axis=1)]
        chosen.append(
            matches.sort_values("time_utc" if "time_utc" in matches else "record_id").iloc[-1]
        )
    return pd.DataFrame(chosen, columns=frame.columns)


def resolve_rows(
    metric: str, rows: pd.DataFrame, devices: pd.DataFrame, settings: Settings
) -> tuple[pd.DataFrame, pd.DataFrame]:
    settings.check_devices(set(devices.device_id))
    if rows.empty:
        frame = rows.copy()
        for column in EXTRA:
            frame[column] = pd.Series(
                dtype={
                    "hour_start_utc": "datetime64[ns, UTC]",
                    "allocation_estimated": "bool",
                }.get(column, "object")
            )
        return frame, frame.assign(selected=pd.Series(dtype=bool), reason="", winner_id="")
    frame = annotate(rows, metric, settings)
    hour_audits = []
    if metric == "calories":
        groups = []
        for kind, group in frame.groupby("kind"):
            priority_metric = f"{kind}_kcal" if f"{kind}_kcal" in settings.priority else metric
            selected_group, hour_audit = hourly(
                group,
                "calories",
                devices,
                Settings(
                    **{
                        **settings.__dict__,
                        "priority": {
                            **settings.priority,
                            "calories": settings.priority.get(priority_metric, []),
                        },
                    }
                ),
            )
            groups.append(selected_group)
            hour_audits.append(hour_audit)
        selected = pd.concat(groups, ignore_index=True)
    elif metric in ("sleep_sessions", "workouts"):
        selected = sessions(frame, metric, devices, settings)
    elif metric in ("resting_heart_rate", "weight", "daily_vendor_summaries"):
        selected = date_values(frame, metric, devices, settings)
    else:
        selected, hour_audit = hourly(frame, metric, devices, settings)
        hour_audits.append(hour_audit)
    audit = frame.copy()
    audit["selected"] = audit["_row"].isin(selected["_row"])
    audit["reason"] = audit["selected"].map({True: "selected", False: "lower priority"})
    if hour_audits:
        records = (
            pd.concat(hour_audits)
            .dropna(subset=["winner_id"])
            .drop_duplicates(["_row", "winner_id"])
            .sort_values("winner_id")
        )
        winners = records.drop_duplicates("_row").set_index("_row").winner_id.copy()
        multiple = records.loc[records._row.duplicated(keep=False)]
        if not multiple.empty:
            combined = multiple.groupby("_row").winner_id.agg(", ".join)
            winners.loc[combined.index] = combined
        audit["winner_id"] = audit["_row"].map(winners).fillna("")
    else:
        audit["winner_id"] = ""
        for index, row in audit.iterrows():
            peers = selected.loc[selected.date_local == row.date_local]
            if "start_utc" in row:
                peers = selected.loc[
                    (selected.start_utc < row.end_utc) & (row.start_utc < selected.end_utc)
                ]
            audit.loc[index, "winner_id"] = ", ".join(sorted(set(peers.physical_device_id)))
    stamp = (
        "time_utc"
        if "time_utc" in selected
        else "start_utc"
        if "start_utc" in selected
        else "date_local"
    )
    columns = [*rows.columns, *[c for c in EXTRA if c not in rows]]
    selected = selected.sort_values([stamp, *SOURCE, "record_id"], kind="stable").reset_index(
        drop=True
    )
    return selected[columns], audit.drop(columns=["_row"])
