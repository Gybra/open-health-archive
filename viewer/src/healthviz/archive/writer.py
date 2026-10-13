import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from healthviz.archive.schema import SCHEMA_VERSION, TABLES, Row, partition_path, sort_key
from healthviz.archive.validate import (
    archive_files,
    safe_track_path,
    validate_archive,
    validate_row,
)


class SchemaMismatch(Exception):
    pass


def existing_rows(root: Path, path: str, columns: tuple[str, ...]) -> list[Row]:
    p = root / path
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != list(columns):
            raise SchemaMismatch(f"{path}: header mismatch")
        return list(reader)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def merge_devices(old: list[Row], new: list[Row]) -> list[Row]:
    rows = {r["device_id"]: r for r in old}
    for row in new:
        previous = rows.get(row["device_id"], {})
        merged = {**previous, **{k: v for k, v in row.items() if v or k not in previous}}
        for col, operation in (("first_seen_utc", min), ("last_seen_utc", max)):
            values = [r[col] for r in (previous, row) if r.get(col)]
            merged[col] = operation(values) if values else ""
        rows[row["device_id"]] = merged
    return sorted(rows.values(), key=lambda r: r["device_id"])


def encode_csv(columns: tuple[str, ...], rows: list[Row]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def record_key(row):
    return row["ingest"], row["record_id"]


def prepare_table(root, name, incoming, delete_keys, replace_sessions):
    t = TABLES[name]
    paths = sorted((root / name).glob("*.csv"))
    groups = {
        p.relative_to(root).as_posix(): existing_rows(
            root, p.relative_to(root).as_posix(), t.columns
        )
        for p in paths
    }
    replaced = {record_key(r) for r in incoming} | delete_keys
    for path, rows in groups.items():
        groups[path] = [
            r
            for r in rows
            if record_key(r) not in replaced
            and not (name == "sleep_stages" and (r["ingest"], r["session_id"]) in replace_sessions)
        ]
    for row in incoming:
        groups.setdefault(partition_path(t, row), []).append(row)
    result = {}
    for path, rows in groups.items():
        keyed = {record_key(r): r for r in rows}
        result[path] = encode_csv(t.columns, sorted(keyed.values(), key=lambda r: sort_key(t, r)))
    return result


def prepare_files(root, tables, devices, delete_keys, replace_sessions):
    prepared = {}
    for name, rows in tables.items():
        if name not in TABLES:
            raise SchemaMismatch("unknown table")
        for row in rows:
            errors = validate_row(TABLES[name], row)
            if errors:
                raise SchemaMismatch(f"{name}: {errors[0]}")
        prepared.update(
            prepare_table(root, name, rows, delete_keys.get(name, set()), replace_sessions)
        )
    if devices:
        t = TABLES["devices"]
        if any(validate_row(t, row) for row in devices):
            raise SchemaMismatch("devices: invalid row")
        merged = merge_devices(existing_rows(root, "devices.csv", t.columns), devices)
        prepared["devices.csv"] = encode_csv(t.columns, merged)
    return prepared


def preflight(root):
    if root.is_symlink() or (root.exists() and any(p.is_symlink() for p in root.rglob("*"))):
        raise SchemaMismatch("archive: symlinks are not allowed")
    if archive_files(root) or (root / "manifest.json").exists():
        errors = validate_archive(root)
        if errors:
            raise SchemaMismatch(f"existing archive failed validation: {errors[0]}")


def manifest_bytes(root, generator):
    files = []
    for path in archive_files(root):
        if path.suffix == ".csv":
            with path.open(newline="", encoding="utf-8") as f:
                rows = max(sum(1 for _ in csv.reader(f)) - 1, 0)
        else:
            rows = None
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": rows,
            }
        )
    manifest = {"schema_version": SCHEMA_VERSION, "generator": generator, "files": files}
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()


def write_archive(
    root: Path,
    tables: dict[str, list[Row]],
    devices: list[Row],
    tracks: dict[str, bytes],
    generator: str,
    *,
    delete_keys=None,
    replace_sessions=None,
) -> None:
    preflight(root)
    if any(not safe_track_path(path) for path in tracks):
        raise SchemaMismatch("unsafe track path")
    # Reconcile owned rows across all partitions before replacing any file.
    prepared = prepare_files(root, tables, devices, delete_keys or {}, replace_sessions or set())
    for rel, data in {**prepared, **tracks}.items():
        target = root / rel
        if not target.exists() or target.read_bytes() != data:
            atomic_write(target, data)
    atomic_write(root / "manifest.json", manifest_bytes(root, generator))
