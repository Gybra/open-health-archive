from datetime import timedelta

import pandas as pd

from healthviz.archive.values import parse_offset


def workout_days(row):
    offset = pd.Timedelta(minutes=parse_offset(row["utc_offset"]))
    start = (row["start_utc"] + offset).date()
    end = (row["end_utc"] + offset - pd.Timedelta(microseconds=1)).date()
    return [day.date() for day in pd.date_range(start, end)]


def split_workout_days(workouts):
    parts = []
    for row in workouts.to_dict("records"):
        days = workout_days(row)
        offset = pd.Timedelta(minutes=parse_offset(row["utc_offset"]))
        elapsed = (row["end_utc"] - row["start_utc"]).total_seconds()
        duration = row["duration_s"] if pd.notna(row["duration_s"]) else elapsed
        for day in days:
            # v1 stores one session offset; allocation cannot reconstruct DST/travel within it.
            midnight = pd.Timestamp(day, tz="UTC") - offset
            start = max(row["start_utc"], midnight)
            end = min(row["end_utc"], midnight + timedelta(days=1))
            parts.append(
                {
                    **row,
                    "date_local": day,
                    "start_utc": start,
                    "end_utc": end,
                    "minutes": duration * (end - start).total_seconds() / elapsed / 60,
                    "allocation_estimated": row["allocation_estimated"] or len(days) > 1,
                    "computed_by": "device" if pd.notna(row["duration_s"]) else "app",
                }
            )
    return pd.DataFrame(parts, columns=[*workouts.columns, "minutes", "computed_by"])
