from dataclasses import asdict, dataclass

from healthviz.archive.schema import TABLES


@dataclass(frozen=True)
class Device:
    device_id: str
    vendor: str
    model: str
    kind: str


def device_rows(devices, tables):
    ranges = {}
    by_id = {d.device_id: d for d in devices.values()}
    for name, rows in tables.items():
        column = TABLES[name].time_column
        for row in rows:
            stamp = row[column]
            if column == "date_local":
                stamp += "T00:00:00Z"
            lo, hi = ranges.get(row["device_id"], (stamp, stamp))
            ranges[row["device_id"]] = (min(lo, stamp), max(hi, stamp))
    result = []
    for identifier, (first, last) in sorted(ranges.items()):
        device = by_id.get(identifier)
        if device:
            result.append({**asdict(device), "first_seen_utc": first, "last_seen_utc": last})
        else:
            result.append(
                dict(
                    device_id=identifier,
                    vendor="",
                    model="",
                    kind="other",
                    first_seen_utc=first,
                    last_seen_utc=last,
                )
            )
    return result
