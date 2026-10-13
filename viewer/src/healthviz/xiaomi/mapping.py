import math

from healthviz.archive.schema import TABLES
from healthviz.archive.validate import validate_row
from healthviz.archive.values import number, utc_iso


class MappingError(ValueError):
    pass


def numeric(value, field: str, required: bool = False):
    n = value.get(field)
    if n is None and not required:
        return None
    if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
        raise MappingError(f"missing or invalid field {field}")
    return n


def timestamp(value, field):
    n = numeric(value, field, required=True)
    if n != int(n):
        raise MappingError(f"invalid timestamp {field}")
    return utc_iso(int(n))


def complete_row(name, values):
    return {**dict.fromkeys(TABLES[name].columns, ""), **values}


def append_row(export, table, line, name, row, output):
    row = complete_row(name, row)
    errors = validate_row(TABLES[name], row)
    if errors:
        export.warn(table, line, errors[0])
        return False
    output.append(row)
    return True


def vendor_minutes(value, field):
    n = numeric(value, field)
    return number(None if n is None else int(n))
