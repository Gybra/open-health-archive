from bisect import bisect_left
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from healthviz.archive.values import parse_offset, parse_utc


class OffsetResolver:
    def __init__(self, zone: ZoneInfo, anchors):
        self.zone = zone
        self.anchors = sorted(anchors)
        self.times = [t for t, _ in self.anchors]

    def home_offset(self, time: int) -> int:
        return int(
            datetime.fromtimestamp(time, UTC).astimezone(self.zone).utcoffset().total_seconds() / 60
        )

    def minutes_at(self, time: int) -> int:
        index = bisect_left(self.times, time)
        neighbours = self.anchors[max(0, index - 1) : index + 1]
        if neighbours:
            stamp, offset = min(neighbours, key=lambda anchor: abs(anchor[0] - time))
            # Travel offsets are estimated within 24h; home-zone DST remains exact.
            if abs(stamp - time) <= 86400 and offset != self.home_offset(stamp):
                return offset
        return self.home_offset(time)


def anchors_from(rows):
    return [(parse_utc(r["start_utc"]), parse_offset(r["utc_offset"])) for r in rows]
