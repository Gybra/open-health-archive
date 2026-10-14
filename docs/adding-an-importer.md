# Adding an importer

An importer turns one source's export into archive schema v1 rows. Everything that is
not source-specific is shared, so a new importer stays small. Two exist:
`healthviz/xiaomi/` (Mi Fitness account export) and `healthviz/health_connect/`
(Health Connect's daily export zip).

1. **Source package.** Create `viewer/src/healthviz/<source>/`. It reads the export
   read-only, treats it as untrusted input, and maps each record to a row of a table in
   `healthviz.archive.schema.TABLES`: metric units, UTC timestamps plus the source
   `utc_offset`, empty fields for unknown values, and `device_id`, `ingest` (for
   example `garmin_export`), `source_app` and a stable `record_id` so a repeated import
   updates rows instead of duplicating them. Device IDs are source-local pseudonyms
   (`healthviz.archive.devices.Device`, `device_rows`); never export account or system
   device identifiers. Error messages are fixed text, never export contents.
2. **Shared writer.** Pass rows, devices and GPX tracks to
   `healthviz.archive.writer.write_archive`. It validates rows, upserts by
   `(ingest, record_id)`, partitions files, writes atomically and the manifest last.
   `delete_keys` and `delete_tracks` remove only the importer's own rows and tracks;
   `journal` lets `recover_archive` undo an interrupted write. Never apply
   cross-source priority: the viewer resolves sources at read time.
3. **Command.** Add an `import <source>` subcommand next to `import xiaomi` and
   `import health-connect` in `viewer/src/healthviz/cli.py`.
4. **App label.** If the source app should appear under a readable name in the
   dashboard's "Apps" filter, add its `source_app` to `healthviz.analysis.apps.LABELS`.
5. **Tests.** Use synthetic fixtures only, cover time zones and daylight saving,
   duplicates, missing values and malformed input, and run the Python gate in Docker.

A watch whose vendor app writes to Health Connect needs no importer: its data arrives
through the Health Connect export.
