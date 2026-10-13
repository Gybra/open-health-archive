# Open Health Archive

A vendor-neutral CSV/GPX archive, a Mi Fitness historical importer, and a local
Docker desktop viewer. Status: early development. The Android Health Connect exporter
is not implemented yet.

## Development

Requires Docker Desktop with Compose. Python and uv stay inside Docker.

```sh
docker compose build
docker compose run --rm dev uv run --no-sync pytest
docker compose run --rm dev uv run --no-sync ruff check .
docker compose run --rm dev uv run --no-sync ruff format --check .
```

Tests run without networking and receive no personal data. The development container
mounts only this repository and runs as an unprivileged user.

## Import a Mi Fitness export

Build the image first with `docker compose build`. Keep private files OUTSIDE this
repository. Choose separate absolute host paths for the extracted export, saved GPX
folder and output archive. Create the output folder yourself before running:

```sh
EXPORT_DIR="/absolute/path/to/extracted-export"
TRACKS_DIR="/absolute/path/to/saved-tracks"
ARCHIVE_DIR="/absolute/path/to/HealthExport"

docker run --rm --network none --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount "type=bind,src=$EXPORT_DIR,dst=/input/export,readonly" \
  --mount "type=bind,src=$TRACKS_DIR,dst=/input/tracks,readonly" \
  --mount "type=bind,src=$ARCHIVE_DIR,dst=/output" \
  open-health-archive-dev uv run --no-sync healthviz import xiaomi /input/export \
  --out /output --tracks-dir /input/tracks --timezone Europe/Rome
```

`--timezone` is required: use your home IANA timezone, not the container's UTC
setting. Vendor offsets take precedence where provided; travel offsets for minute
samples are estimates based on nearby sleep/workout records. Minute interval ends
are inferred as timestamp +60 seconds; confirm them against vendor documentation
before comparing fine-grained interval data across manufacturers.

The importer also accepts a ZIP without extracting it. Re-imports upsert the same
records across partitions and preserve other ingestion sources. Corrected sessions
replace their owned sleep stages; corrected steps can retract derived distance.
Device IDs are stable source-local pseudonyms, not model names or anonymization.
Associating the same physical watch across different adapters requires explicit
mapping; it cannot be inferred safely from names. Track backups use `<Time>.gpx` names.
If a GPX backup is missing, the importer attempts the vendor download URL: that needs
network access and the link may have expired. The offline command above instead
reports a missing track and continues. Never mount originals writable or mount your
home or Docker socket.

See `schema/export-schema.md` for the contract. Error messages omit input values;
record counts and warning counts are printed. Existing archives must validate before
any update. If an archive is corrupt or an interrupted import left an inconsistent
manifest, rebuild to a NEW output folder and retain the old folder for inspection;
never silently repair or overwrite it. Do not run concurrent imports to the same
archive. Store the output privately and back it up.

## Consult an archive locally

Keep the archive and personal configuration outside this repository. Google Drive
files must be fully available locally before mounting them. Create a private config
directory (only this directory is mounted, not your home):

```sh
mkdir -p "$HOME/.config/healthviz"
chmod 700 "$HOME/.config/healthviz"
docker compose build
HEALTHVIZ_ARCHIVE_DIR="/absolute/path/to/HealthExport" docker compose up -d viewer
```

Open `http://127.0.0.1:8501`. Without `HEALTHVIZ_ARCHIVE_DIR`, the viewer uses the
clearly labeled synthetic demonstration archive. Set `HEALTHVIZ_CONFIG_DIR` to choose
another private settings directory. The archive is mounted read-only. Settings are
saved separately in `config.toml`; source associations must be explicit, never based
on identical model names. Advanced per-device ingest orders can be edited in the
private TOML `[ingest_priority]` table.

Offline consultation disables all basemap requests:

```sh
HEALTHVIZ_ARCHIVE_DIR="/absolute/path/to/HealthExport" docker compose run --rm \
  --service-ports viewer healthviz view /archive --container \
  --config /config/config.toml --offline
```

Stop an existing viewer first with `docker compose stop viewer` to free port 8501.
The host binding remains loopback; `--lan` never changes Docker port publication.
Daily coverage is hours containing heart-rate samples, not verified wear time.
Incomplete days and absent values are not zero and do not enter eligible means.
Recorded offsets can be estimates and cannot describe a timezone change within one
long session. Cross-hour interval allocation is proportional and marked estimated.
Overnight workout minutes are also allocated proportionally across local midnights.
Period `complete` describes HR coverage only; each metric additionally reports its
eligible covered-day count and completeness. Partial totals are never extrapolated.
CSV downloads include the selected period only; rolling chart means use preceding
history outside the visible range. Plotly charts offer PNG downloads.
Vendor fallback is never added to raw data. Do not import or sync files while
consulting; a changing/inconsistent snapshot is rejected rather than silently read.

## Privacy

Archives are plaintext. A cloud storage provider can read them if you sync them to
Google Drive or another service. Healthviz does not upload files. GPS tracks reveal
locations: keep archives private and backed up. Online maps request OSM tiles in
the browser, revealing the viewed area to that provider; `--offline` uses no basemap.
Streamlit telemetry and remote deployment controls are disabled. A standard-library
audit hook blocks Python socket connections and outbound DNS before framework
startup; it is not a sandbox for arbitrary native code. No health-data disk cache
or persistent database is created. Keep sync/import jobs stopped while consulting.
Containers protect original exports
only when they are mounted read-only; Docker does not encrypt them.

This is not a medical device and provides no diagnosis or medical advice.
