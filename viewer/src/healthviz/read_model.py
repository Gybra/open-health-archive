"""Opt-in local read model; the CSV/GPX archive is always authoritative."""

import fcntl
import hashlib
import itertools
import json
import multiprocessing
import os
import re
import stat
import sys
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import duckdb
import pandas as pd

from healthviz import read_model_store as store
from healthviz.analysis.apps import app_choices, select_apps
from healthviz.analysis.daily import daily_summary
from healthviz.analysis.sleep import sleep_summary
from healthviz.analysis.sources import resolve_rows
from healthviz.archive.reader import ArchiveReadError, load_archive, verify_snapshot
from healthviz.archive.validate import file_checksum
from healthviz.settings import Settings, load_settings


class ReadModelError(Exception):
    pass


# Frames read from published files, kept while each file is untouched; refreshes and new tabs
# reuse them instead of reading the cache again.
loaded = {}
GENERATION = r"generation-[0-9a-f]{32}\.duckdb"
# One app choice's derived frames over the generation's raw tables.
RESULTS = r"derived-[0-9a-f]{32}\.duckdb"
DIGEST = r"[0-9a-f]{64}"
MAX_RESULTS = 64
# Up to this many apps every combination is prepared ahead (63 results); beyond, each app alone.
MAX_ALL_APPS = 6


def stamp(path: Path):
    value = path.stat()
    return str(path), value.st_ino, value.st_size, value.st_mtime_ns


def remember(path: Path, checksum: str, state) -> None:
    global loaded
    loaded = {
        **{k: v for k, v in loaded.items() if k[0] != str(path)},
        (*stamp(path), checksum): state,
    }


def forget(cache: Path, keep: set[str]) -> None:
    global loaded
    loaded = {
        k: v for k, v in loaded.items() if Path(k[0]).parent != cache or Path(k[0]).name in keep
    }


def read_generation(path: Path, checksum: str):
    key = (*stamp(path), checksum)
    if key in loaded:
        return loaded[key]
    if file_checksum(path) != checksum:
        return None
    state = store.read_frames(path)
    if file_checksum(path) != checksum:
        return None
    remember(path, checksum, state)
    return state


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
                # Apps are a set: the order they were picked in must not miss the cache.
                asdict(replace(settings, apps=sorted(settings.apps))),
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
    for name in (".lock", ".precompute.lock", "current.json"):
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


def pointer_of(cache):
    pointer_path = cache / "current.json"
    private_path(pointer_path)
    if pointer_path.stat().st_size > 64 * 1024:
        return None
    pointer = json.loads(pointer_path.read_bytes())
    results = pointer.get("derived", []) if isinstance(pointer, dict) else None
    if (
        not isinstance(pointer, dict)
        or not {"file", "sha256"} <= set(pointer) <= {"file", "sha256", "derived"}
        or not re.fullmatch(GENERATION, pointer["file"])
        or not re.fullmatch(DIGEST, pointer["sha256"])
        or not isinstance(results, list)
        or len(results) > MAX_RESULTS
        or not all(
            isinstance(entry, dict)
            and set(entry) == {"key", "file", "sha256"}
            and re.fullmatch(DIGEST, entry["key"])
            and re.fullmatch(RESULTS, entry["file"])
            and re.fullmatch(DIGEST, entry["sha256"])
            for entry in results
        )
    ):
        return None
    forget(cache, {pointer["file"], *(entry["file"] for entry in results)})
    return pointer


def read_file(cache, name, checksum):
    path = cache / name
    private_path(path)
    spill = Path(str(path) + ".tmp")
    if spill.exists() or spill.is_symlink():
        private_path(spill, directory=True)
    wal = Path(str(path) + ".wal")
    if wal.exists() or wal.is_symlink():
        private_path(wal)
        return None
    return read_generation(path, checksum)


def current(cache):
    try:
        pointer = pointer_of(cache)
        state = None if pointer is None else read_file(cache, pointer["file"], pointer["sha256"])
        return None if state is None else (pointer, *state)
    except (OSError, ValueError, KeyError, TypeError, duckdb.Error):
        return None


def raw(frames):
    return {k: v for k, v in frames.items() if not k.startswith("derived_")}


def lookup(cache, derived_key):
    """The published generation, and the frames for this settings choice when already built."""
    found = current(cache)
    if found is None:
        return None, None
    pointer, metadata, frames = found
    if metadata["derived_key"] == derived_key:
        return found, frames
    for entry in pointer.get("derived", []):
        if entry["key"] == derived_key:
            try:
                extra = read_file(cache, entry["file"], entry["sha256"])
            except (OSError, ValueError, KeyError, TypeError, duckdb.Error):
                extra = None
            if extra is not None and (extra[0]["raw_key"], extra[0]["derived_key"]) == (
                metadata["raw_key"],
                derived_key,
            ):
                return found, {**raw(frames), **extra[1]}
    return found, None


def result(snapshot, frames):
    # Shallow copies: with copy-on-write, a session's edits never reach the shared frames.
    frames = {k: v.copy(deep=False) for k, v in frames.items()}
    return ReadModel(
        *snapshot,
        raw(frames),
        frames["derived_daily"],
        frames["derived_sleep"],
        frames["derived_workouts"],
    )


def derive(tables, settings):
    settings.check_devices(set(tables["devices"].device_id))
    chosen = select_apps(tables, settings.apps)
    daily = daily_summary(chosen, tables["devices"], settings)
    sessions, _ = resolve_rows(
        "sleep_sessions", chosen["sleep_sessions"], tables["devices"], settings
    )
    workouts, _ = resolve_rows("workouts", chosen["workouts"], tables["devices"], settings)
    return {
        **tables,
        "derived_daily": daily,
        "derived_sleep": sleep_summary(sessions, chosen["sleep_stages"]),
        "derived_workouts": workouts,
    }


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def cleanup(cache, keep: set[str]):
    pattern = (
        r"(?:\.building-)?(?:generation|derived)-[0-9a-f]{32}\.duckdb(?:\.wal)?|"
        r"\.pointer-[0-9a-f]{32}"
    )
    spill_pattern = r"(?:\.building-)?(?:generation|derived)-[0-9a-f]{32}\.duckdb\.tmp"
    for path in cache.iterdir():
        # One undeletable entry must not strand the remaining obsolete plaintext copies.
        try:
            if re.fullmatch(spill_pattern, path.name):
                private_path(path, directory=True)
                for part in path.iterdir():
                    if re.fullmatch(r"duckdb_temp_storage_[A-Za-z0-9_-]+\.tmp", part.name):
                        private_path(part)
                        part.unlink()
                # Unrecognized spill files are kept; never let them block publication.
                if not any(path.iterdir()):
                    path.rmdir()
            elif path.name not in keep and re.fullmatch(pattern, path.name):
                private_path(path)
                path.unlink()
        except OSError:
            continue
    fsync_directory(cache)


def write_file(cache, prefix, frames, raw_key, derived_key, root, snapshot):
    name = f"{prefix}-{uuid.uuid4().hex}.duckdb"
    candidate = cache / (".building-" + name)
    if candidate.exists():
        raise OSError("candidate already exists")
    try:
        store.write_frames(candidate, frames, raw_key, derived_key)
        state = store.read_frames(candidate)
        if verify_snapshot(root) != snapshot:
            raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        checksum = file_checksum(candidate)
        os.replace(candidate, cache / name)
        fsync_directory(cache)
        remember(cache / name, checksum, state)
        return name, checksum
    finally:
        candidate.unlink(missing_ok=True)
        Path(str(candidate) + ".wal").unlink(missing_ok=True)


def point(cache, pointer):
    path = cache / (".pointer-" + uuid.uuid4().hex)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(pointer, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(path, cache / "current.json")
    fsync_directory(cache)
    try:
        cleanup(cache, {pointer["file"], *(e["file"] for e in pointer.get("derived", []))})
    except OSError:
        pass  # The new pointer is published; leftovers are retried next publication.


def publish(cache, frames, raw_key, derived_key, root, snapshot):
    name, checksum = write_file(cache, "generation", frames, raw_key, derived_key, root, snapshot)
    point(cache, {"file": name, "sha256": checksum})


def publish_results(cache, pointer, frames, raw_key, derived_key, root, snapshot):
    """Add one more app choice to the published generation without rewriting its raw tables."""
    results = {k: v for k, v in frames.items() if k.startswith("derived_")}
    name, checksum = write_file(cache, "derived", results, raw_key, derived_key, root, snapshot)
    earlier = [e for e in pointer.get("derived", []) if e["key"] != derived_key]
    entry = {"key": derived_key, "file": name, "sha256": checksum}
    point(
        cache,
        {
            "file": pointer["file"],
            "sha256": pointer["sha256"],
            "derived": [*earlier, entry][-MAX_RESULTS:],
        },
    )


def load_read_model(
    root: Path, settings: Settings, *, cache_dir: Path, config: Path, on_build=lambda: None
) -> ReadModel:
    # Keep restrictive permissions process-wide; restoring umask races other sessions.
    os.umask(0o077)
    try:
        validate_location(cache_dir, root, config)
        snapshot = verify_snapshot(root)
        raw_key, derived_key = keys(snapshot[1], settings)
        with locked(cache_dir, exclusive=False):
            _, frames = lookup(cache_dir, derived_key)
            if frames is not None:
                settings.check_devices(set(frames["devices"].device_id))
                if verify_snapshot(root) != snapshot:
                    raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
                return result(snapshot, frames)
        with locked(cache_dir, exclusive=True):
            if verify_snapshot(root) != snapshot:
                raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
            found, frames = lookup(cache_dir, derived_key)
            if frames is not None:
                settings.check_devices(set(frames["devices"].device_id))
                if verify_snapshot(root) != snapshot:
                    raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
                return result(snapshot, frames)
            on_build()
            if found is not None and found[1]["raw_key"] == raw_key:
                # Shallow copies: derivation must not touch the frames other sessions share.
                tables = {k: v.copy(deep=False) for k, v in raw(found[2]).items()}
                frames = derive(tables, settings)
                publish_results(cache_dir, found[0], frames, raw_key, derived_key, root, snapshot)
            else:
                frames = derive(load_archive(root), settings)
                publish(cache_dir, frames, raw_key, derived_key, root, snapshot)
            return result(snapshot, frames)
    except (OSError, ValueError, KeyError, TypeError, duckdb.Error):
        raise ReadModelError(
            "cache: cannot prepare local read model; check private directory"
        ) from None


def app_subsets(choices: list[str]) -> list[list[str]]:
    """App choices to prepare ahead, all apps first and then from single apps up."""
    labels = sorted(choices)
    sizes = range(1, len(labels)) if len(labels) <= MAX_ALL_APPS else [1]
    return [[], *[list(c) for size in sizes for c in itertools.combinations(labels, size)]]


def same_except_apps(left: Settings, right: Settings) -> bool:
    return replace(left, apps=[]) == replace(right, apps=[])


def prepare_choices(root: Path, cache: Path, config: Path) -> None:
    validate_location(cache, root, config)
    settings = load_settings(config)
    snapshot = verify_snapshot(root)
    raw_key, _ = keys(snapshot[1], settings)
    with locked(cache, exclusive=False):
        found = current(cache)
    if found is None or found[1]["raw_key"] != raw_key:
        return
    tables = raw(found[2])
    for apps in app_subsets(app_choices(tables)):
        # Picking other apps is what this prepares for; any other change makes it stale.
        if not same_except_apps(load_settings(config), settings):
            return
        chosen = replace(settings, apps=apps)
        derived_key = keys(snapshot[1], chosen)[1]
        with locked(cache, exclusive=False):
            if lookup(cache, derived_key)[1] is not None:
                continue
        frames = derive({k: v.copy(deep=False) for k, v in tables.items()}, chosen)
        with locked(cache, exclusive=True):
            if verify_snapshot(root) != snapshot:
                return
            latest, done = lookup(cache, derived_key)
            if latest is None or latest[0]["file"] != found[0]["file"]:
                return
            if done is None:
                publish_results(cache, latest[0], frames, raw_key, derived_key, root, snapshot)


def precompute(root: Path, cache: Path, config: Path) -> None:
    """Prepare other app choices in a low-priority process, one run per cache at a time."""
    os.umask(0o077)
    os.nice(10)
    fd = os.open(cache / ".precompute.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        private_path(cache / ".precompute.lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            prepare_choices(root, cache, config)
        except (OSError, ValueError, KeyError, TypeError, duckdb.Error, ArchiveReadError):
            return  # Only a head start: the viewer builds any missing choice when it is picked.


# Background runs already started by this viewer process, by data and settings other than apps.
started = {}


def start_precompute(root: Path, cache: Path, config: Path, content_digest: str, settings):
    key = (str(cache), content_digest, keys(content_digest, replace(settings, apps=[]))[1])
    if key in started:
        # shortcut: a run stopped by a settings change is not restarted if those settings come
        # back in the same viewer process; missing choices are still built when picked.
        return None
    multiprocessing.active_children()  # reap finished runs
    # spawn, not fork: the server process already runs threads.
    process = multiprocessing.get_context("spawn").Process(
        target=precompute, args=(root, cache, config), daemon=True
    )
    process.start()
    started[key] = process
    return process
