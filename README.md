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

## Privacy

Archives are plaintext. A cloud storage provider can read them if you sync them to
Google Drive or another service. Healthviz does not upload files. GPS tracks reveal
locations: keep archives private and backed up. Containers protect original exports
only when they are mounted read-only; Docker does not encrypt them.

This is not a medical device and provides no diagnosis or medical advice.
