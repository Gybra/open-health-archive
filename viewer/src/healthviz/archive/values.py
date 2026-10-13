import math
import re
from datetime import UTC, datetime, timedelta


def utc_iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(text: str) -> int:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text):
        raise ValueError("expected UTC timestamp")
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def offset_text(minutes: int) -> str:
    if abs(minutes) > 14 * 60:
        raise ValueError("invalid offset")
    hours, mins = divmod(abs(minutes), 60)
    return f"{'-' if minutes < 0 else '+'}{hours:02}:{mins:02}"


def parse_offset(text: str) -> int:
    if not re.fullmatch(r"[+-]\d{2}:\d{2}", text):
        raise ValueError("invalid offset")
    hours, minutes = map(int, text[1:].split(":"))
    if minutes >= 60 or hours > 14 or (hours == 14 and minutes):
        raise ValueError("invalid offset")
    return (hours * 60 + minutes) * (-1 if text[0] == "-" else 1)


def local_date(utc_text: str, offset: str) -> str:
    instant = datetime.fromtimestamp(parse_utc(utc_text), UTC)
    return (instant + timedelta(minutes=parse_offset(offset))).date().isoformat()


def number(value: int | float | None) -> str:
    if value is None:
        return ""
    if not math.isfinite(value):
        raise ValueError("nonfinite number")
    return str(value) if isinstance(value, int) else f"{value:.1f}"


def positive(value: int | float | None) -> str:
    return "" if value is None or value <= 0 else number(value)
