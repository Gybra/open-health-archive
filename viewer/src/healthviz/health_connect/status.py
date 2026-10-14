"""Outcome of the last import, read by the dashboard: names and counts, never health values."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ImportStatus:
    folder: str = ""
    zip_name: str = ""
    zip_sha256: str = ""
    imported_at: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    not_imported: dict[str, int] = field(default_factory=dict)
    format_version: int | None = None
    format_tested: bool = True
    error: str | None = None
    already_imported: bool = False
    # zip_name, zip_sha256, imported_at and the archive manifest's SHA-256 after that import.
    last_success: dict | None = None


def load_status(path: Path) -> ImportStatus | None:
    try:
        return ImportStatus(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return None


def save_status(path: Path, status: ImportStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".status-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(asdict(status), out, indent=2, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
