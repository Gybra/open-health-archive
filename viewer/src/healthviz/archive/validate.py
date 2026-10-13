import csv
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path, PurePosixPath

from healthviz.archive.schema import (
    COLUMN_KINDS,
    SCHEMA_VERSION,
    TABLES,
    Row,
    Table,
    partition_path,
)
from healthviz.archive.values import parse_offset, parse_utc


def safe_track_path(text: str) -> bool:
    p = PurePosixPath(text)
    return (
        not p.is_absolute()
        and len(p.parts) == 2
        and p.parts[0] == "tracks"
        and p.suffix == ".gpx"
        and ".." not in p.parts
        and "\\" not in text
    )


def check_value(kind: str, value: str) -> None:
    if kind == "utc":
        parse_utc(value)
    elif kind == "offset":
        parse_offset(value)
    elif kind == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("date")
        date.fromisoformat(value)
    elif kind in ("number", "int"):
        n = int(value) if kind == "int" else float(value)
        if not math.isfinite(n) or n < 0:
            raise ValueError("number")
    elif kind == "bool" and value not in ("true", "false"):
        raise ValueError("boolean")


def validate_row(t: Table, row: Row) -> list[str]:
    errors = []
    if set(row) != set(t.columns):
        return ["row columns do not match schema"]
    for col in t.columns:
        value = row[col]
        if not isinstance(value, str):
            errors.append(f"{col}: expected text")
            continue
        if not value:
            if col in t.required:
                errors.append(f"{col} is required")
            continue
        try:
            check_value(COLUMN_KINDS.get(col, "text"), value)
        except (ValueError, OverflowError):
            errors.append(f"{col}: invalid value")
        if col in t.enums and value not in t.enums[col]:
            errors.append(f"{col}: invalid enum")
    if row.get("start_utc") and row.get("end_utc") and row["end_utc"] <= row["start_utc"]:
        errors.append("invalid interval")
    if row.get("track_file") and not safe_track_path(row["track_file"]):
        errors.append("track_file: unsafe path")
    return errors


def check_csv(root: Path, path: Path, seen: set) -> list[str]:
    rel = path.relative_to(root).as_posix()
    name = rel.split("/")[0].removesuffix(".csv")
    if name not in TABLES:
        return [f"{rel}: unknown table"]
    t, errors = TABLES[name], []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != list(t.columns):
            return [f"{rel}:1: header mismatch"]
        for line, row in enumerate(reader, 2):
            problems = validate_row(t, row)
            if not problems and partition_path(t, row) != rel:
                problems.append("wrong partition")
            key = (name, row.get("ingest"), row.get("record_id", row.get("device_id")))
            if key in seen:
                problems.append("duplicate record")
            seen.add(key)
            track = row.get("track_file")
            if track and safe_track_path(track) and not (root / track).is_file():
                problems.append("missing track file")
            errors.extend(f"{rel}:{line}: {e}" for e in problems)
    return errors


def archive_files(root: Path) -> list[Path]:
    return sorted([*root.rglob("*.csv"), *root.glob("tracks/*.gpx")])


def validate_archive(root: Path) -> list[str]:
    files, errors, seen = archive_files(root), [], set()
    if any(p.is_symlink() for p in root.rglob("*")):
        return ["archive: symlinks are not allowed"]
    for p in files:
        if p.suffix == ".csv":
            errors.extend(check_csv(root, p, seen))
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["schema_version"] != SCHEMA_VERSION:
            errors.append("manifest: schema version mismatch")
        entries = {f["path"]: f for f in manifest["files"]}
        if set(entries) != {p.relative_to(root).as_posix() for p in files}:
            errors.append("manifest: file list mismatch")
        for p in files:
            rel = p.relative_to(root).as_posix()
            if (
                rel in entries
                and hashlib.sha256(p.read_bytes()).hexdigest() != entries[rel]["sha256"]
            ):
                errors.append(f"{rel}: checksum mismatch")
    except (OSError, ValueError, KeyError, TypeError):
        errors.append("manifest: missing or invalid")
    return errors
