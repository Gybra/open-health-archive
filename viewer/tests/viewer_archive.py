from copy import deepcopy

from fixture_archive import FIXTURE_DEVICES, FIXTURE_TABLES, FIXTURE_TRACKS

from healthviz.archive.writer import write_archive


def write_viewer_archive(root, **table_overrides):
    tables = deepcopy(FIXTURE_TABLES)
    tables.update(table_overrides)
    write_archive(root, tables, deepcopy(FIXTURE_DEVICES), FIXTURE_TRACKS, "synthetic viewer")
    return root
