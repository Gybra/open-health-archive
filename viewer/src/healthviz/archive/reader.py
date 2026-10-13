import fcntl
import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path

import duckdb
import pandas as pd

from healthviz.archive.schema import COLUMN_KINDS, TABLES
from healthviz.archive.validate import archive_files, check_csv, check_manifest, read_regular_bytes


class ArchiveReadError(Exception):
    pass


def archive_token(root: Path) -> str:
    try:
        digest = hashlib.sha256(read_regular_bytes(root / "manifest.json"))
        for path in [root, *sorted(root.rglob("*"))]:
            if path.is_symlink():
                raise ArchiveReadError("archive: symlinks are not allowed")
            stat = path.stat()
            digest.update(f"{path.relative_to(root)}:{stat.st_size}:{stat.st_mtime_ns}".encode())
        return digest.hexdigest()
    except OSError:
        raise ArchiveReadError("archive: cannot read snapshot") from None


def verify_snapshot(root: Path) -> tuple[str, str]:
    """Verify source bytes even when metadata is unchanged; never parse cached CSVs."""
    try:
        token = archive_token(root)
        manifest = read_regular_bytes(root / "manifest.json")
        files = archive_files(root)
        if check_manifest(root, files, manifest):
            raise ArchiveReadError("archive: validation failed; finish sync and reload")
        if (
            archive_token(root) != token
            or read_regular_bytes(root / "manifest.json") != manifest
            or archive_token(root) != token
        ):
            raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
        return token, hashlib.sha256(manifest).hexdigest()
    except ArchiveReadError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise ArchiveReadError("archive: cannot verify snapshot") from None


def typed_frame(frame: pd.DataFrame) -> pd.DataFrame:
    for col in frame:
        kind = COLUMN_KINDS.get(col)
        if kind in ("int", "number"):
            frame[col] = pd.to_numeric(frame[col]).astype("Int64" if kind == "int" else "Float64")
        elif kind == "utc":
            frame[col] = pd.to_datetime(frame[col], utc=True)
        elif kind == "date":
            frame[col] = pd.to_datetime(frame[col]).dt.date
        elif kind == "bool":
            frame[col] = frame[col].map({"true": True, "false": False}).astype("boolean")
        else:
            frame[col] = frame[col].astype("string")
    return frame


def sealed_csv(root, path, expected_hash, seen, buffers):
    data = read_regular_bytes(path)
    if check_csv(root, path, seen, data) or hashlib.sha256(data).hexdigest() != expected_hash:
        raise ArchiveReadError(
            "archive: validation failed; finish sync or rebuild into a new folder"
        )
    # Linux sealed anonymous buffers bind validation and DuckDB to identical bytes.
    fd = os.memfd_create("healthviz-csv", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    buffer = buffers.enter_context(os.fdopen(fd, "w+b"))
    buffer.write(data)
    buffer.flush()
    fcntl.fcntl(
        fd,
        fcntl.F_ADD_SEALS,
        fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
    )
    return f"/proc/self/fd/{fd}"


def load_archive(root: Path) -> dict[str, pd.DataFrame]:
    try:
        token = archive_token(root)
        files = archive_files(root)
        manifest = json.loads(read_regular_bytes(root / "manifest.json"))
        hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
        if check_manifest(root, files):
            raise ArchiveReadError(
                "archive: validation failed; finish sync or rebuild into a new folder"
            )
        frames, paths_by_table, seen = {}, {}, set()
        for path in files:
            if path.suffix == ".csv":
                name = path.relative_to(root).parts[0].removesuffix(".csv")
                if name not in TABLES:
                    raise ArchiveReadError("archive: validation failed; unknown table")
                paths_by_table.setdefault(name, []).append(path)
        with duckdb.connect() as conn:
            for name, table in TABLES.items():
                sources, parts = paths_by_table.get(name, []), []
                # Bound open descriptors and close each batch after materialization.
                for start in range(0, len(sources), 16):
                    with ExitStack() as buffers:
                        paths = [
                            sealed_csv(
                                root, path, hashes[path.relative_to(root).as_posix()], seen, buffers
                            )
                            for path in sources[start : start + 16]
                        ]
                        parts.append(
                            conn.read_csv(
                                paths,
                                header=True,
                                auto_detect=False,
                                columns=dict.fromkeys(table.columns, "VARCHAR"),
                            ).fetchdf()
                        )
                frame = (
                    pd.concat(parts, ignore_index=True)
                    if parts
                    else pd.DataFrame(columns=table.columns)
                )
                frames[name] = typed_frame(frame)
        # Writers replace files individually. Never cache a mixed or still-changing snapshot.
        # Unchanged checksums preserve validated rows; do not parse every CSV again.
        if (
            archive_token(root) != token
            or check_manifest(root, archive_files(root))
            or archive_token(root) != token
        ):
            raise ArchiveReadError("archive: snapshot changed; finish sync and reload")
        ids = set(frames["devices"]["device_id"])
        if any(
            not set(frame["device_id"]).issubset(ids)
            for name, frame in frames.items()
            if name != "devices"
        ):
            raise ArchiveReadError("archive: record references an unknown source")
        return frames
    except ArchiveReadError:
        raise
    except (OSError, ValueError, TypeError, KeyError, duckdb.Error):
        raise ArchiveReadError("archive: cannot read validated snapshot") from None
