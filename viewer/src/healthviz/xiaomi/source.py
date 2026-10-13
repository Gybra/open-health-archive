import csv
import io
import json
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

REQUIRED_COLUMNS = {
    "data_source": {"Sid", "Model", "Name"},
    "fitness_data": {"Sid", "Key", "Time", "Value"},
    "aggregated_fitness_data": {"Sid", "Tag", "Key", "Time", "Value"},
    "sport_record": {"Sid", "Key", "Time", "Value"},
    "sport_track_data": {"Time", "GPX"},
}


class ExportError(Exception):
    pass


class XiaomiExport:
    def __init__(self, path: Path, files: dict[str, str]):
        self.path, self.files = path, files
        self.warnings: list[str] = []
        self.reported: set[str] = set()

    @contextmanager
    def stream(self, table):
        if self.path.is_dir():
            with (self.path / self.files[table]).open(encoding="utf-8-sig", newline="") as f:
                yield f
        else:
            with zipfile.ZipFile(self.path) as z, z.open(self.files[table]) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as f:
                    yield f

    def has(self, table: str) -> bool:
        return table in self.files

    def warn(self, table: str, row: int, reason: str) -> None:
        self.warnings.append(f"{table}.csv:{row}: {reason}")

    def warn_once(self, table: str, reason: str) -> None:
        text = f"{table}.csv: {reason}"
        if text not in self.reported:
            self.reported.add(text)
            self.warnings.append(text)

    def rows(self, table):
        if table not in self.files:
            self.warn_once(table, "not found")
            return
        with self.stream(table) as f:
            for n, row in enumerate(csv.DictReader(f), 1):
                if None in row or any(v is None for v in row.values()):
                    self.warn(table, n, "malformed CSV row")
                    continue
                yield n, row

    def json_value(self, table, row, text):
        try:
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            self.warn(table, row, "invalid JSON")
            return None


def open_export(path: Path) -> XiaomiExport:
    path = Path(path)
    csv.field_size_limit(sys.maxsize)
    if path.is_dir():
        names = [p.name for p in path.glob("*.csv") if not p.is_symlink()]
    elif path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    else:
        raise ExportError("export: not a directory or ZIP")
    files = {}
    for table in REQUIRED_COLUMNS:
        matches = [n for n in names if n.endswith(f"_hlth_center_{table}.csv")]
        if len(matches) > 1:
            raise ExportError(f"{table}.csv: ambiguous file")
        if matches:
            files[table] = matches[0]
        elif table in ("data_source", "fitness_data"):
            raise ExportError(f"{table}.csv: not found")
    export = XiaomiExport(path, files)
    for table in files:
        with export.stream(table) as f:
            fields = next(csv.reader(f), [])
            if not REQUIRED_COLUMNS[table] <= set(fields):
                raise ExportError(f"{table}.csv: missing required columns")
    return export
