import csv
import hashlib
import io
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from healthviz.archive.schema import SCHEMA_VERSION, TABLES, Row, partition_path, sort_key
from healthviz.archive.validate import archive_files, safe_track_path, validate_row


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


def prepare_files(root: Path, tables: dict[str, list[Row]], devices: list[Row]) -> dict[str, bytes]:
    groups = defaultdict(list)
    for name, rows in {**tables, "devices": devices}.items():
        if name not in TABLES:
            raise SchemaMismatch("unknown table")
        t = TABLES[name]
        for row in rows:
            errors = validate_row(t, row)
            if errors:
                raise SchemaMismatch(f"{name}: {errors[0]}")
            groups[partition_path(t, row)].append(row)
    result = {}
    for path, incoming in groups.items():
        name = path.split("/")[0].removesuffix(".csv")
        t = TABLES[name]
        old = existing_rows(root, path, t.columns)
        if any(validate_row(t, row) for row in old):
            raise SchemaMismatch(f"{path}: invalid existing row")
        if name == "devices":
            merged = merge_devices(old, incoming)
        else:
            keyed = {(r["ingest"], r["record_id"]): r for r in old + incoming}
            merged = sorted(keyed.values(), key=lambda row: sort_key(t, row))
        result[path] = encode_csv(t.columns, merged)
    return result


def write_archive(
    root: Path,
    tables: dict[str, list[Row]],
    devices: list[Row],
    tracks: dict[str, bytes],
    generator: str,
) -> None:
    if root.is_symlink() or (root.exists() and any(p.is_symlink() for p in root.rglob("*"))):
        raise SchemaMismatch("archive: symlinks are not allowed")
    if any(not safe_track_path(path) for path in tracks):
        raise SchemaMismatch("unsafe track path")
    if (root / "manifest.json").exists():
        try:
            version = json.loads((root / "manifest.json").read_text())["schema_version"]
            if version != SCHEMA_VERSION:
                raise SchemaMismatch("manifest: unsupported schema version")
        except (ValueError, KeyError) as e:
            raise SchemaMismatch("manifest: invalid") from e
    # Preflight every touched CSV before replacing any file.
    prepared = prepare_files(root, tables, devices)
    for rel, data in {**prepared, **tracks}.items():
        target = root / rel
        if not target.exists() or target.read_bytes() != data:
            atomic_write(target, data)
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
    atomic_write(
        root / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
