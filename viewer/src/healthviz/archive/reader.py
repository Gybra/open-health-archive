import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from healthviz.archive.schema import COLUMN_KINDS, TABLES
from healthviz.archive.validate import archive_files, validate_archive


class ArchiveReadError(Exception):
    pass


def archive_token(root: Path) -> str:
    try:
        digest = hashlib.sha256((root / "manifest.json").read_bytes())
        for path in [root, *sorted(root.rglob("*"))]:
            if path.is_symlink():
                raise ArchiveReadError("archive: symlinks are not allowed")
            stat = path.stat()
            digest.update(f"{path.relative_to(root)}:{stat.st_size}:{stat.st_mtime_ns}".encode())
        return digest.hexdigest()
    except OSError:
        raise ArchiveReadError("archive: cannot read snapshot") from None


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


def load_archive(root: Path) -> dict[str, pd.DataFrame]:
    try:
        token = archive_token(root)
        if validate_archive(root):
            raise ArchiveReadError(
                "archive: validation failed; finish sync or rebuild into a new folder"
            )
        frames = {}
        with duckdb.connect() as conn:
            for name, table in TABLES.items():
                paths = [
                    str(p)
                    for p in archive_files(root)
                    if p.suffix == ".csv"
                    and (p.stem if p.parent == root else p.parent.name) == name
                ]
                frame = (
                    conn.read_csv(
                        paths, header=True, columns=dict.fromkeys(table.columns, "VARCHAR")
                    ).fetchdf()
                    if paths
                    else pd.DataFrame(columns=table.columns)
                )
                frames[name] = typed_frame(frame)
        # Writers replace files individually. Never cache a mixed or still-changing snapshot.
        if validate_archive(root) or archive_token(root) != token:
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
