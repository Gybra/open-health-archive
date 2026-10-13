import pandas as pd

from healthviz.archive.values import parse_offset

STAGES = ["deep", "light", "rem", "awake", "unknown"]
SLEEP_COLUMNS = [
    "date_local",
    "main",
    "sleep_min",
    "elapsed_min",
    "uncovered_min",
    "onset_wall_min",
    "wake_wall_min",
    "eligible",
    "completeness",
    *[f"{s}_share" for s in STAGES],
]


def session_stages(session, stages):
    return stages.loc[
        (stages.session_id == session["session_id"])
        & (stages.ingest == session["ingest"])
        & (stages.device_id == session["device_id"])
    ].sort_values("start_utc")


def sleep_summary(sessions: pd.DataFrame, stages: pd.DataFrame) -> pd.DataFrame:
    if sessions.empty:
        return pd.DataFrame(
            columns=[*sessions.columns, *[c for c in SLEEP_COLUMNS if c not in sessions]]
        )
    output = []
    for session in sessions.to_dict("records"):
        elapsed = (session["end_utc"] - session["start_utc"]).total_seconds() / 60
        row = {**session, "elapsed_min": elapsed}
        state = session.get("is_complete")
        row["completeness"] = "unknown" if pd.isna(state) else "complete" if state else "incomplete"
        ambiguous = session.get("quality") == "ambiguous"
        if session["has_stages"]:
            parts = session_stages(session, stages).copy()
            parts["start_utc"] = parts.start_utc.clip(lower=session["start_utc"])
            parts["end_utc"] = parts.end_utc.clip(upper=session["end_utc"])
            parts = parts.loc[parts.end_utc > parts.start_utc]
            ambiguous |= (parts.start_utc < parts.end_utc.cummax().shift()).any()
            parts["minutes"] = (parts.end_utc - parts.start_utc).dt.total_seconds() / 60
            totals = parts.groupby("stage").minutes.sum()
            for stage in STAGES:
                row[f"{stage}_min"] = totals.get(stage, None)
        else:
            row["unknown_min"] = None
        measured = [row.get(f"{s}_min") for s in ("deep", "light", "rem")]
        measured = [v for v in measured if pd.notna(v)]
        row["sleep_min"] = sum(measured) if measured and not ambiguous else None
        known_total = sum(v for s in STAGES if pd.notna(v := row.get(f"{s}_min")))
        row["uncovered_min"] = max(0, elapsed - known_total)
        row["eligible"] = (
            row["completeness"] != "incomplete"
            and not ambiguous
            and row["sleep_min"] is not None
            and row["uncovered_min"] <= 1
            and (pd.isna(row.get("unknown_min")) or row["unknown_min"] == 0)
        )
        offset = pd.Timedelta(minutes=parse_offset(session["utc_offset"]))
        start, end = session["start_utc"] + offset, session["end_utc"] + offset
        row["date_local"] = end.date()
        row["onset_wall_min"] = start.hour * 60 + start.minute
        row["wake_wall_min"] = end.hour * 60 + end.minute
        for stage in STAGES:
            value = row.get(f"{stage}_min")
            row[f"{stage}_share"] = (
                value / known_total
                if pd.notna(value) and known_total > 0 and not ambiguous
                else None
            )
        output.append(row)
    result = pd.DataFrame(output).sort_values(
        ["date_local", "elapsed_min", "start_utc", "record_id"],
        ascending=[True, False, True, True],
        kind="stable",
    )
    result["main"] = ~result.date_local.duplicated()
    return result.reset_index(drop=True)
