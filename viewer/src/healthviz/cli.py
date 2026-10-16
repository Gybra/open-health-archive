import argparse
import csv
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from healthviz.archive.writer import SchemaMismatch
from healthviz.settings import SettingsError, load_settings
from healthviz.xiaomi.importer import import_xiaomi
from healthviz.xiaomi.source import ExportError


def zone_for(timezone: str | None, config: Path | None) -> ZoneInfo:
    """The IANA zone an import needs: the explicit one, else the private config's."""
    name = timezone or (load_settings(config).default_timezone if config else None)
    if name is None:
        raise SettingsError("give --timezone or --config")
    return ZoneInfo(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local, vendor-neutral health archives")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import").add_subparsers(dest="vendor", required=True)
    xiaomi = importer.add_parser("xiaomi")
    xiaomi.add_argument("export", type=Path)
    xiaomi.add_argument("--out", type=Path, required=True)
    xiaomi.add_argument("--tracks-dir", type=Path)
    # A container's timezone is not the user's; explicit IANA zone avoids silent UTC defaults.
    xiaomi.add_argument("--timezone", help="IANA zone, e.g. Europe/Rome")
    xiaomi.add_argument("--config", type=Path, help="Use its fallback timezone")
    health_connect = importer.add_parser("health-connect")
    health_connect.add_argument("source", type=Path, help="Export zip or the folder holding it")
    health_connect.add_argument("--out", type=Path, required=True)
    health_connect.add_argument("--status", type=Path, required=True)
    health_connect.add_argument("--journal", type=Path, required=True)
    health_connect.add_argument("--timezone", help="IANA zone for records without an offset")
    health_connect.add_argument("--config", type=Path, help="Use its fallback timezone")
    health_connect.add_argument("--label", default="", help="Folder name shown in the dashboard")
    viewer = commands.add_parser("view", help="Consult a local archive")
    viewer.add_argument("archive", nargs="?", type=Path)
    viewer.add_argument(
        "--config", type=Path, default=Path.home() / ".config/healthviz/config.toml"
    )
    viewer.add_argument(
        "--cache-dir", type=Path, help="Opt in to a separate private local read model"
    )
    viewer.add_argument("--offline", action="store_true")
    viewer.add_argument("--lan", action="store_true")
    viewer.add_argument("--container", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == "view":
        from healthviz.launch import view

        return view(
            args.archive,
            config=args.config,
            offline=args.offline,
            lan=args.lan,
            container=args.container,
            cache_dir=args.cache_dir,
        )
    if args.vendor == "health-connect":
        return import_health_connect_command(args)
    try:
        result = import_xiaomi(
            args.export,
            args.out,
            zone=zone_for(args.timezone, args.config),
            tracks_dir=args.tracks_dir,
        )
    except (ZoneInfoNotFoundError, ValueError):
        print("import failed: unknown timezone", file=sys.stderr)
        return 1
    except SettingsError as error:
        print(f"import failed: {error}", file=sys.stderr)
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


def import_health_connect_command(args) -> int:
    from healthviz.health_connect.importer import import_health_connect

    try:
        zone = zone_for(args.timezone, args.config)
    except (ZoneInfoNotFoundError, ValueError):
        print("import failed: unknown timezone", file=sys.stderr)
        return 1
    except SettingsError as error:
        print(f"import failed: {error}", file=sys.stderr)
        return 1
    status = import_health_connect(
        args.source, args.out, zone=zone, status=args.status, journal=args.journal, label=args.label
    )
    if status.error:
        print(f"import failed: {status.error}", file=sys.stderr)
        return 1
    if status.already_imported:
        print("already imported")
        return 0
    for table, count in status.counts.items():
        print(f"{table}: {count}")
    for table, count in status.skipped.items():
        print(f"skipped {table}: {count}")
    for kind, count in status.not_imported.items():
        print(f"not imported {kind}: {count}")
    return 0
