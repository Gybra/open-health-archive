"""Opt-in local read model; the CSV/GPX archive is always authoritative."""

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import pandas as pd

from healthviz import read_model_store as store
from healthviz.analysis.daily import daily_summary
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.reader import ArchiveReadError, load_archive, verify_snapshot
from healthviz.archive.validate import file_checksum
from healthviz.settings import Settings


class ReadModelError(Exception):
    pass


@dataclass(frozen=True)
class ReadModel:
    source_token: str
    content_digest: str
    tables: dict[str, pd.DataFrame]
    daily: pd.DataFrame
    sleep: pd.DataFrame
    workouts: pd.DataFrame


def fingerprint(paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def keys(content_digest, settings):
    package = Path(__file__).parent
    raw = hashlib.sha256(
        json.dumps(
            [
                content_digest,
                store.FORMAT_VERSION,
                sys.version_info[:3],
                duckdb.__version__,
                pd.__version__,
                fingerprint(
                    [
                        package / "read_model_store.py",
                        *[
                            package / "archive" / name
                            for name in ("schema.py", "reader.py", "validate.py", "values.py")
                        ],
                    ]
                ),
            ]
        ).encode()
    ).hexdigest()
    derived = hashlib.sha256(
        json.dumps(
            [
                raw,
                asdict(settings),
                fingerprint(
                    [
                        Path(__file__),
                        package / "settings.py",
                        *list((package / "analysis").glob("*.py")),
                    ]
                ),
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return raw, derived


def private_path(path: Path, *, directory=False):
    value = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    mode = 0o700 if directory else 0o600
    if (
        not kind(value.st_mode)
        or stat.S_IMODE(value.st_mode) != mode
        or value.st_uid != os.geteuid()
    ):
        raise ReadModelError("cache: require an owned private directory and files")


def validate_location(cache: Path, root: Path, config: Path):
    if any(p.is_symlink() for p in (cache, *cache.parents)):
        raise ReadModelError("cache: symlinks are not allowed")
    private_path(cache, directory=True)
    resolved = cache.resolve()
    for blocked in (root.resolve(), config.parent.resolve(), Path(__file__).resolve().parents[3]):
        if resolved.is_relative_to(blocked) or blocked.is_relative_to(resolved):
            raise ReadModelError("cache: use a separate directory outside archive, config and code")
        if blocked.exists() and os.path.samefile(cache, blocked):
            raise ReadModelError("cache: directory aliases a protected location")
    for name in (".lock", "current.json"):
        path = cache / name
        if path.exists() or path.is_symlink():
            private_path(path)


@contextmanager
def locked(cache: Path, *, exclusive: bool):
    fd = os.open(cache / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        private_path(cache / ".lock")
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def current(cache):
    try:
        pointer_path = cache / "current.json"
        private_path(pointer_path)
        if pointer_path.stat().st_size > 1024:
            return None
        pointer = json.loads(pointer_path.read_bytes())
        if (
            set(pointer) != {"file", "sha256"}
            or not re.fullmatch(r"generation-[0-9a-f]{32}\.duckdb", pointer["file"])
            or not re.fullmatch(r"[0-9a-f]{64}", pointer["sha256"])
        ):
            return None
        path = cache / pointer["file"]
        private_path(path)
        spill = Path(str(path) + ".tmp")
        if spill.exists() or spill.is_symlink():
            private_path(spill, directory=True)
        wal = Path(str(path) + ".wal")
        if wal.exists() or wal.is_symlink():
            private_path(wal)
            return None
        if file_checksum(path) != pointer["sha256"]:
            return None
        metadata, frames = store.read_frames(path)
        if file_checksum(path) != pointer["sha256"]:
            return None
        return metadata, frames
    except (OSError, ValueError, KeyError, TypeError, duckdb.Error):
        return None


def result(snapshot, frames):
    return ReadModel(
        *snapshot,
        {k: v for k, v in frames.items() if not k.startswith("derived_")},
        frames["derived_daily"],
        frames["derived_sleep"],
        frames["derived_workouts"],
    )


def derive(tables, settings):
    settings.check_devices(set(tables["devices"].device_id))
    daily = daily_summary(tables, tables["devices"], settings)
    sessions, _ = resolve_rows(
        "sleep_sessions", tables["sleep_sessions"], tables["devices"], settings
    )
    workouts, _ = resolve_rows("workouts", tables["workouts"], tables["devices"], settings)
    return {
        **tables,
        "derived_daily": daily,
        "derived_sleep": sleep_summary(sessions, tables["sleep_stages"]),
        "derived_workouts": workouts,
    }


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def cleanup(cache, keep):
    pattern = (
        r"(?:generation-[0-9a-f]{32}\.duckdb(?:\.wal)?|"
        r"\.building-generation-[0-9a-f]{32}\.duckdb(?:\.wal)?|\.pointer-[0-9a-f]{32})"
    )
    spill_pattern = r"(?:\.building-)?generation-[0-9a-f]{32}\.duckdb\.tmp"
    for path in cache.iterdir():
        if re.fullmatch(spill_pattern, path.name):
            private_path(path, directory=True)
            for part in path.iterdir():
                if re.fullmatch(r"duckdb_temp_storage_[A-Za-z0-9_-]+\.tmp", part.name):
                    private_path(part)
                    part.unlink()
            # Unrecognized spill files are kept; never let them block publication.
            if not any(path.iterdir()):
                path.rmdir()
        elif path.name != keep and re.fullmatch(pattern, path.name):
            private_path(path)
            path.unlink()
    fsync_directory(cache)


def publish(cache, frames, raw_key, derived_key, root, snapshot):
    name = f"generation-{uuid.uuid4().hex}.duckdb"
    candidate = cache / (".building-" + name)
    if candidate.exists():
        raise OSError("candidate already exists")
    try:
        store.write_frames(candidate, frames, raw_key, derived_key)
        store.read_frames(candidate)
        if verify_snapshot(root) != snapshot:
            raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        checksum = file_checksum(candidate)
        os.replace(candidate, cache / name)
        fsync_directory(cache)
        pointer = cache / (".pointer-" + uuid.uuid4().hex)
        fd = os.open(pointer, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"file": name, "sha256": checksum}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pointer, cache / "current.json")
        fsync_directory(cache)
        try:
            cleanup(cache, name)
        except OSError:
            pass  # The new generation is published; leftovers are retried next publication.

    finally:
        candidate.unlink(missing_ok=True)
        Path(str(candidate) + ".wal").unlink(missing_ok=True)


def load_read_model(root: Path, settings: Settings, *, cache_dir: Path, config: Path) -> ReadModel:
    # Keep restrictive permissions process-wide; restoring umask races other sessions.
    os.umask(0o077)
    try:
        validate_location(cache_dir, root, config)
        snapshot = verify_snapshot(root)
        raw_key, derived_key = keys(snapshot[1], settings)
        with locked(cache_dir, exclusive=False):
            state = current(cache_dir)
            if state is not None and state[0]["derived_key"] == derived_key:
                settings.check_devices(set(state[1]["devices"].device_id))
                if verify_snapshot(root) != snapshot:
                    raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
                return result(snapshot, state[1])
        with locked(cache_dir, exclusive=True):
            if verify_snapshot(root) != snapshot:
                raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
            state = current(cache_dir)
            if state is not None and state[0]["derived_key"] == derived_key:
                settings.check_devices(set(state[1]["devices"].device_id))
                if verify_snapshot(root) != snapshot:
                    raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
                return result(snapshot, state[1])
            tables = (
                result(snapshot, state[1]).tables
                if state is not None and state[0]["raw_key"] == raw_key
                else load_archive(root)
            )
            frames = derive(tables, settings)
            publish(cache_dir, frames, raw_key, derived_key, root, snapshot)
            return result(snapshot, frames)
    except (OSError, ValueError, KeyError, TypeError, duckdb.Error):
        raise ReadModelError(
            "cache: cannot prepare local read model; check private directory"
        ) from None
