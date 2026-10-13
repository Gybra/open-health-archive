import argparse
import csv
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from healthviz.archive.writer import SchemaMismatch
from healthviz.xiaomi.importer import import_xiaomi
from healthviz.xiaomi.source import ExportError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local, vendor-neutral health archives")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import").add_subparsers(dest="vendor", required=True)
    xiaomi = importer.add_parser("xiaomi")
    xiaomi.add_argument("export", type=Path)
    xiaomi.add_argument("--out", type=Path, required=True)
    xiaomi.add_argument("--tracks-dir", type=Path)
    # A container's timezone is not the user's; explicit IANA zone avoids silent UTC defaults.
    xiaomi.add_argument("--timezone", required=True, help="IANA zone, e.g. Europe/Rome")
    args = parser.parse_args(argv)
    try:
        result = import_xiaomi(
            args.export, args.out, zone=ZoneInfo(args.timezone), tracks_dir=args.tracks_dir
        )
    except ZoneInfoNotFoundError:
        print("import failed: unknown timezone", file=sys.stderr)
        return 1
    except (ExportError, SchemaMismatch) as error:
        print(f"import failed: {error}", file=sys.stderr)
        return 1
    except (OSError, csv.Error, UnicodeError, zipfile.BadZipFile):
        # Third-party exception messages may contain filenames or private input.
        print("import failed: cannot read input or write archive", file=sys.stderr)
        return 1
    for table, count in sorted(result.counts.items()):
        print(f"{table}: {count}")
    print(f"tracks linked: {result.tracks_linked}; missing: {result.tracks_missing}")
    print(f"warnings: {len(result.warnings)}")
    for warning in result.warnings[:50]:
        print(warning, file=sys.stderr)
    return 0
