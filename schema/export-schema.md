# Archive schema v1

UTF-8 CSV, comma delimiter, RFC 4180 quoting, header row and LF line endings.
One row per observation; UTC timestamps use ISO 8601 with Z. utc_offset is the
source's offset (+HH:MM), or an importer estimate when the vendor omits it.
Empty means unknown, never zero. Numeric values use metric units: m, seconds,
minutes, bpm, kcal, kg and saturation percent, as indicated by column names.

Provenance: device_id identifies the measurement source, ingest the ingestion path,
source_app the originating application, and record_id an idempotent record key.
The Xiaomi importer uses source-local hashed pseudonyms so two identical models or
renamed devices do not collide. Names/models remain metadata. These pseudonyms are
not anonymization; cross-ingest identity requires an explicit source association,
not matching names. Vendor aggregate sources may lack physical-device attribution.
Account IDs and source system device identifiers are never exported. source_type
preserves the original sleep stage or exercise label. computed_by distinguishes
device observations, vendor calculations and app-derived values.

High-volume tables are partitioned by UTC month; low-volume tables by year.
Date-only tables use their explicit local date. devices.csv is unpartitioned.
Writers preserve all sources. Cross-source priority belongs to the reader.
Only vendor resting HR and explicitly flagged daily fallback summaries are kept
as precomputed aggregates. Fallback suppression is per source, metric and local day;
a steps observation without distance must not suppress distance fallback. The viewer
must select between raw observations and summaries, never add both.
Sleep is_complete is optional: false means explicitly incomplete; empty means unknown.

Writes upsert by (ingest, record_id); devices merge by device_id. Individual files
are replaced atomically, manifest.json last. Readers must verify the manifest
before accepting a snapshot: individual atomic replacements are not a whole-folder
transaction. manifest.json has schema_version, generator and a sorted files list,
with path, sha256 and rows (null for GPX). No volatile creation timestamp.

GPX tracks live under tracks/<workout_id>.gpx; optional elevation/time data is
preserved. A workout's track_file is a relative path, never a signed vendor URL.

## devices

Partition: single.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| device_id | text | yes |  |
| vendor | text | no |  |
| model | text | no |  |
| kind | text | yes | app, manual, other, phone, watch |
| first_seen_utc | utc | no |  |
| last_seen_utc | utc | no |  |

## heart_rate

Partition: month.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| time_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| bpm | int | yes |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## steps

Partition: month.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| start_utc | utc | yes |  |
| end_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| count | int | yes |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## distance

Partition: month.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| start_utc | utc | yes |  |
| end_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| distance_m | number | yes |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## calories

Partition: month.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| start_utc | utc | yes |  |
| end_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| kind | text | yes | active, total |
| kcal | number | yes |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## sleep_stages

Partition: month.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| session_id | text | yes |  |
| start_utc | utc | yes |  |
| end_utc | utc | yes |  |
| stage | text | yes | awake, deep, light, rem, unknown |
| source_type | text | no |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## sleep_sessions

Partition: year.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| session_id | text | yes |  |
| start_utc | utc | yes |  |
| end_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| has_stages | bool | yes |  |
| is_complete | bool | no |  |
| deep_min | int | no |  |
| light_min | int | no |  |
| rem_min | int | no |  |
| awake_min | int | no |  |
| computed_by | text | yes | app, device, vendor |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## workouts

Partition: year.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| workout_id | text | yes |  |
| type | text | yes |  |
| source_type | text | no |  |
| start_utc | utc | yes |  |
| end_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| duration_s | int | no |  |
| distance_m | number | no |  |
| steps | int | no |  |
| active_kcal | number | no |  |
| total_kcal | number | no |  |
| avg_hr | int | no |  |
| max_hr | int | no |  |
| ascent_m | number | no |  |
| descent_m | number | no |  |
| ascent_computed_by | text | no | app, device, vendor |
| track_file | text | no |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## resting_heart_rate

Partition: year.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| date_local | date | yes |  |
| bpm | int | yes |  |
| computed_by | text | yes | app, device, vendor |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## spo2

Partition: year.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| time_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| percent | number | yes |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## weight

Partition: year.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| time_utc | utc | yes |  |
| utc_offset | offset | yes |  |
| kg | number | yes |  |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## daily_vendor_summaries

Partition: year.

| Column | Type | Required | Allowed values |
|---|---|---|---|
| date_local | date | yes |  |
| metric | text | yes | active_kcal, distance, sleep_duration, steps |
| value | number | yes |  |
| unit | text | yes |  |
| computed_by | text | yes | vendor |
| device_id | text | yes |  |
| ingest | text | yes |  |
| source_app | text | no |  |
| record_id | text | yes |  |

## Synthetic examples

See schema/fixtures/archive for a complete valid archive with every table,
a staged night, a vendor-summary night, and workouts with and without GPS.
Never replace these fictional rows with real health records.
