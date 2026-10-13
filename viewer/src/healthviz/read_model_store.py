"""Primitive frame storage for disposable, immutable viewer generations."""

import json
from datetime import date
from numbers import Real
from pathlib import Path

import duckdb
import pandas as pd

from healthviz.analysis.daily import METRICS
from healthviz.analysis.sleep import SLEEP_COLUMNS, STAGES
from healthviz.analysis.sources import EXTRA
from healthviz.archive.schema import TABLES

FORMAT_VERSION = 1
DTYPES = {
    "object",
    "str",
    "string",
    "Int64",
    "Float64",
    "boolean",
    "int64",
    "float64",
    "bool",
    "datetime64[ns, UTC]",
    "datetime64[us, UTC]",
    "datetime64[ms, UTC]",
    "datetime64[s, UTC]",
}
SQL_TYPES = {
    "text": "VARCHAR",
    "date": "VARCHAR",
    "time": "BIGINT",
    "int": "BIGINT",
    "float": "DOUBLE",
    "bool": "BOOLEAN",
}


def connection(path: Path, *, read_only: bool):
    return duckdb.connect(
        str(path),
        read_only=read_only,
        config={
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    )


def encode_series(series):
    dtype = str(series.dtype)
    if dtype not in DTYPES:
        raise ValueError("unsupported cache dtype")
    if dtype.startswith("datetime64"):
        values = series.astype("datetime64[ns, UTC]").astype("int64").astype("Int64")
        return "time", values.mask(series.isna())
    if dtype in ("Int64", "int64"):
        return "int", series
    if dtype in ("Float64", "float64"):
        return "float", series
    if dtype in ("boolean", "bool"):
        return "bool", series
    if dtype == "object":
        values = series.dropna()
        if not values.empty and isinstance(values.iloc[0], date):
            return "date", series.map(lambda v: v.isoformat() if pd.notna(v) else None)
        if not values.empty and all(isinstance(v, Real) for v in values):
            kind = "int" if all(isinstance(v, int) for v in values) else "float"
            return kind, series
        if not values.empty and not all(isinstance(v, str) for v in values):
            raise ValueError("unsupported cache objects")
    return "text", series


def write_frames(path: Path, frames: dict, raw_key: str, derived_key: str):
    metadata = {
        "version": FORMAT_VERSION,
        "raw_key": raw_key,
        "derived_key": derived_key,
        "frames": {},
    }
    with connection(path, read_only=False) as conn:
        conn.execute("BEGIN")
        for name, frame in frames.items():
            encoded = pd.DataFrame({"_order": range(len(frame))})
            columns = []
            for column in frame:
                kind, values = encode_series(frame[column])
                encoded[column] = values
                columns.append(
                    {
                        "name": column,
                        "dtype": str(frame[column].dtype),
                        "kind": kind,
                        "missing_na": any(v is pd.NA for v in frame[column]),
                    }
                )
            metadata["frames"][name] = {"columns": columns, "rows": len(frame)}
            conn.register("input_frame", encoded)
            casts = [
                f'CAST("{c["name"]}" AS {SQL_TYPES[c["kind"]]}) AS "{c["name"]}"' for c in columns
            ]
            conn.execute(
                f'CREATE TABLE "{name}" AS SELECT _order, {", ".join(casts)} FROM input_frame'
            )
            conn.unregister("input_frame")
        conn.execute("CREATE TABLE healthviz_meta (payload VARCHAR)")
        conn.execute("INSERT INTO healthviz_meta VALUES (?)", [json.dumps(metadata)])
        conn.execute("COMMIT")
        conn.execute("CHECKPOINT")


def validate_metadata(conn, metadata):
    daily = {"date_local", "worn_hours", "complete", "sleep_eligible", *METRICS}
    for metric in METRICS:
        daily.update(
            f"{metric}_{suffix}"
            for suffix in ("physical_device_id", "computed_by", "quality", "fallback")
        )
    allowed = {name: set(table.columns) for name, table in TABLES.items()}
    allowed.update(
        {
            "derived_daily": daily,
            "derived_sleep": set(TABLES["sleep_sessions"].columns)
            | set(EXTRA)
            | set(SLEEP_COLUMNS)
            | {f"{stage}_min" for stage in STAGES},
            "derived_workouts": set(TABLES["workouts"].columns) | set(EXTRA),
        }
    )
    if (
        not isinstance(metadata, dict)
        or set(metadata) != {"version", "raw_key", "derived_key", "frames"}
        or not isinstance(metadata["frames"], dict)
        or metadata["version"] != FORMAT_VERSION
        or set(metadata["frames"]) != set(allowed)
    ):
        raise ValueError("unsupported cache contract")
    catalog = conn.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_catalog = current_database()"
    ).fetchall()
    if set(catalog) != {(name, "BASE TABLE") for name in [*allowed, "healthviz_meta"]}:
        raise ValueError("unexpected cache catalog")
    if conn.execute(
        "SELECT count(*) FROM duckdb_functions() WHERE database_name = current_database() "
        "AND function_type IN ('macro', 'table_macro')"
    ).fetchone()[0]:
        raise ValueError("unexpected cache macro")
    for name, description in metadata["frames"].items():
        columns = description["columns"]
        names = [c["name"] for c in columns]
        if (
            len(names) != len(set(names))
            or not set(names).issubset(allowed[name])
            or type(description["rows"]) is not int
            or description["rows"] < 0
        ):
            raise ValueError("invalid cache columns")
        if name in TABLES and names != list(TABLES[name].columns):
            raise ValueError("invalid raw cache columns")
        for c in columns:
            if (
                c["dtype"] not in DTYPES
                or c["kind"] not in SQL_TYPES
                or type(c["missing_na"]) is not bool
            ):
                raise ValueError("unsupported cache types")
        actual = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_catalog = current_database() AND table_name = ? "
            "ORDER BY ordinal_position",
            [name],
        ).fetchall()
        expected = [("_order", "BIGINT"), *[(c["name"], SQL_TYPES[c["kind"]]) for c in columns]]
        if actual != expected:
            raise ValueError("invalid physical cache schema")
        count, distinct, minimum, maximum = conn.execute(
            f'SELECT count(*), count(DISTINCT _order), min(_order), max(_order) FROM "{name}"'
        ).fetchone()
        if (
            count != description["rows"]
            or count != distinct
            or (count and (minimum != 0 or maximum != count - 1))
        ):
            raise ValueError("invalid cache rows")


def read_frames(path: Path) -> tuple[dict, dict]:
    with connection(path, read_only=True) as conn:
        payloads = conn.execute("SELECT payload FROM healthviz_meta").fetchall()
        if len(payloads) != 1:
            raise ValueError("invalid cache metadata")
        metadata = json.loads(payloads[0][0])
        validate_metadata(conn, metadata)
        frames = {}
        for name, description in metadata["frames"].items():
            columns = description["columns"]
            values = conn.execute(f'SELECT * FROM "{name}" ORDER BY _order').fetchall()
            frame = pd.DataFrame()
            for index, column in enumerate(columns, 1):
                data = [row[index] for row in values]
                dtype, kind = column["dtype"], column["kind"]
                if dtype not in DTYPES or kind not in SQL_TYPES:
                    raise ValueError("unsupported cache dtype")
                if kind == "time":
                    series = pd.to_datetime(pd.Series(data, dtype="Int64"), unit="ns", utc=True)
                    frame[column["name"]] = series.astype(dtype)
                elif kind == "date":
                    frame[column["name"]] = pd.Series(
                        [date.fromisoformat(v) if v is not None else None for v in data],
                        dtype=dtype,
                    )
                else:
                    if dtype == "object" and column["missing_na"]:
                        data = [pd.NA if v is None else v for v in data]
                    frame[column["name"]] = pd.Series(data, dtype=dtype)
            frames[name] = frame
        return metadata, frames
