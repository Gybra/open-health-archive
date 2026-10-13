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
another private settings directory. The archive is mounted read-only. In the Linux Docker runtime, validated CSV input
buffers stay in memory and are released after each bounded batch; no temporary CSV
cache is written to disk. Settings are saved separately in `config.toml`; source associations must be explicit, never based
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

## Optional persistent local preparation

By default the viewer creates no persistent health-data database. To speed up new
sessions and process restarts, explicitly enable a disposable DuckDB read model.
CSV/GPX and the manifest remain canonical; deleting this cache loses no archive data.
It stores a **second plaintext copy** of raw tables, daily summaries and Overview
sleep/workout context. It does not store GPX points, map density or observation messages.

Choose a separate directory outside the repository, archive and configuration, and
outside automatic Drive/iCloud sync. Check local backup policy too. On macOS the
recommended location is `$HOME/Library/Caches/OpenHealthArchive/viewer`. Keep the
parent private, then create the empty viewer directory using the non-root container
identity (Docker Desktop may report a host-created directory with a different UID):

```sh
CACHE_PARENT="$HOME/Library/Caches/OpenHealthArchive"
mkdir -p "$CACHE_PARENT"
chmod 700 "$CACHE_PARENT"
docker run --rm --network none --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount "type=bind,src=$CACHE_PARENT,dst=/cache-parent" \
  open-health-archive-viewer python -c \
  'import os; os.mkdir("/cache-parent/viewer", 0o700)'

HEALTHVIZ_ARCHIVE_DIR="/absolute/path/to/HealthExport" \
HEALTHVIZ_CACHE_DIR="$CACHE_PARENT/viewer" \
  docker compose -f compose.yaml -f compose.cache.yaml up -d viewer
```

Create the directory only once; do not overwrite an existing directory or change
archive/config permissions to fix access. The cache requires an owned directory with
mode `0700` and generated files with mode `0600`. Unsafe paths, symlinks, shared
permissions and archive/config/code overlap are refused. The overlay requires an
explicit `HEALTHVIZ_CACHE_DIR` and never creates a missing host directory automatically.
The archive stays read-only, configuration stays separate, and only `/cache` is added.
Never mount the home directory or Docker socket. Bind aliases/nesting outside the
container namespace cannot all be detected: verify all three **host** paths are disjoint.

For offline cached consultation, use the same two Compose files and environment
variables with `run --rm --service-ports viewer healthviz view /archive --container
--config /config/config.toml --cache-dir /cache --offline` instead of `up`. Stop an
existing viewer yourself before reusing port 8501; the overlay retains loopback binding.
Omit the overlay and `--cache-dir` to keep the original nonpersistent mode.

First preparation may be slower; later starts skip CSV parsing and full daily analysis.
Every rerun still hashes current CSV/GPX content, and disk hits verify the DB before
and after materialization. This is not an mtime shortcut and not a promise of a
particular speedup. Changed sources/settings/code invalidate preparation; settings
or analysis-only changes can reuse validated raw tables. Filters and historical end
dates remain computed on demand using full-history inputs. First Map use still parses
tracks and computes density.

Only completed immutable generations are published. Threads/processes coordinate
through file locks; interrupted builds and corrupt DBs rebuild from a valid archive.
An invalid/changing archive never falls back to an old DB. Stop sync/import jobs
while consulting. Replacement temporarily needs space for old and new generations.
Cache errors do not repair or modify the archive or settings.

To force a fresh preparation, stop cache-using viewers and remove only generated
files in this dedicated cache directory; retain the directory and its permissions.
Disabling persistence does not remove old cache files. File deletion is not secure
erasure and does not delete OS/back-up copies. Protect this directory like the archive.

## Privacy

Archives are plaintext. A cloud storage provider can read them if you sync them to
Google Drive or another service. Healthviz does not upload files. GPS tracks reveal
locations: keep archives private and backed up. Online maps request OSM tiles in
the browser, revealing the viewed area to that provider; `--offline` uses no basemap.
Streamlit telemetry and remote deployment controls are disabled. A standard-library
audit hook blocks Python socket connections and outbound DNS before framework
startup; it is not a sandbox for arbitrary native code. No persistent health-data
cache is created unless `--cache-dir` is explicitly enabled; the optional read model
is a separate disposable plaintext copy, not an upload or a replacement archive.
Keep sync/import jobs stopped while consulting.
Containers protect original exports
only when they are mounted read-only; Docker does not encrypt them.

This is not a medical device and provides no diagnosis or medical advice.
