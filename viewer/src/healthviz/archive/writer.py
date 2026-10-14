import csv
import hashlib
import io
import json
import os
import shutil
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


def save_journal(root: Path, journal: Path, paths: list[str]) -> None:
    """Keep every target's previous bytes so an interrupted write can be undone."""
    (journal / "blobs").mkdir(parents=True, mode=0o700)
    journal.chmod(0o700)
    entries = []
    for number, rel in enumerate(paths):
        existed = (root / rel).exists()
        if existed:
            blob = journal / "blobs" / str(number)
            with blob.open("wb") as f:
                f.write((root / rel).read_bytes())
                f.flush()
                os.fsync(f.fileno())
        entries.append({"path": rel, "existed": existed})
    # The entry list is written last and atomically: without it nothing was replaced yet.
    partial = journal / "entries.json.partial"
    with partial.open("w") as f:
        json.dump(entries, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(partial, journal / "entries.json")


def journaled_manifest(journal: Path, entries: list[dict]) -> bytes | None:
    number = next(i for i, e in enumerate(entries) if e["path"] == "manifest.json")
    return (journal / "blobs" / str(number)).read_bytes() if entries[number]["existed"] else None


def discard_journal(journal: Path) -> None:
    # Remove the entry list first, so a half-deleted journal is never replayed.
    (journal / "entries.json").unlink(missing_ok=True)
    shutil.rmtree(journal)


def recover_archive(root: Path, journal: Path) -> bool:
    """Undo an interrupted write recorded in journal; True when files were restored.

    The manifest is replaced last, so an interrupted write still has the manifest the
    journal saved. Any other manifest means the write finished, someone wrote since, or
    this is a different archive: the journal no longer describes it and is dropped.
    """
    if not journal.exists():
        return False
    try:
        entries = json.loads((journal / "entries.json").read_text())
        before = journaled_manifest(journal, entries)
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        discard_journal(journal)
        return False
    manifest = root / "manifest.json"
    if (manifest.read_bytes() if manifest.exists() else None) != before:
        discard_journal(journal)
        return False
    for number, entry in enumerate(entries):
        target = root / entry["path"]
        if entry["existed"]:
            atomic_write(target, (journal / "blobs" / str(number)).read_bytes())
        elif target.exists():
            target.unlink()
    discard_journal(journal)
    return True


def write_archive(
    root: Path,
    tables: dict[str, list[Row]],
    devices: list[Row],
    tracks: dict[str, bytes],
    generator: str,
    *,
    delete_keys=None,
    replace_sessions=None,
    delete_tracks: set[str] | None = None,
    journal: Path | None = None,
) -> None:
    if journal is not None and journal.exists():
        raise SchemaMismatch("archive: interrupted import must be recovered first")
    if journal is not None and journal.resolve().is_relative_to(root.resolve()):
        raise SchemaMismatch("archive: journal must live outside the archive")
    preflight(root)
    removed = set(delete_tracks or ())
    if any(not safe_track_path(path) for path in [*tracks, *removed]):
        raise SchemaMismatch("unsafe track path")
    # Reconcile owned rows across all partitions before replacing any file.
    prepared = prepare_files(root, tables, devices, delete_keys or {}, replace_sessions or set())
    changed = {
        rel: data
        for rel, data in {**prepared, **tracks}.items()
        if not (root / rel).exists() or (root / rel).read_bytes() != data
    }
    removed = sorted(p for p in removed if p not in tracks and (root / p).exists())
    if journal is not None:
        save_journal(root, journal, [*changed, *removed, "manifest.json"])
    for rel, data in changed.items():
        atomic_write(root / rel, data)
    for rel in removed:
        (root / rel).unlink()
    atomic_write(root / "manifest.json", manifest_bytes(root, generator))
    if journal is not None:
        discard_journal(journal)
