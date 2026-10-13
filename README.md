# Open Health Archive

A vendor-neutral CSV/GPX archive, a Mi Fitness historical importer, and a planned local
desktop viewer. Status: early development. The Android Health Connect exporter and
viewer are not implemented yet.

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
home or Docker socket. The viewer is not available in this milestone.

See `schema/export-schema.md` for the contract. Error messages omit input values;
record counts and warning counts are printed. Existing archives must validate before
any update. If an archive is corrupt or an interrupted import left an inconsistent
manifest, rebuild to a NEW output folder and retain the old folder for inspection;
never silently repair or overwrite it. Do not run concurrent imports to the same
archive. Store the output privately and back it up.

## Privacy

Archives are plaintext. A cloud storage provider can read them if you sync them to
Google Drive or another service. Healthviz does not upload files. GPS tracks reveal
locations: keep archives private and backed up. Containers protect original exports
only when they are mounted read-only; Docker does not encrypt them.

This is not a medical device and provides no diagnosis or medical advice.
