# General Software Engineering Principles

These rules are mandatory for every code change, regardless of language, framework, or project. Do not treat them as optional suggestions.

Before writing code, understand the requirement and the relevant existing code. Do not proceed with the first plausible idea without checking whether an existing, simpler, or more direct solution would work better. Choose the smallest solution that fully meets the need. If a rule cannot be followed, explain why before proceeding.

## Choose the Smallest Correct Solution

You MUST implement the simplest solution that fully meets the requirement.

You MUST NOT add abstractions, layers, helpers, configuration, indirection, or generalized infrastructure for hypothetical future needs. Add them only when they provide a concrete benefit to the current work, such as correctness, security, necessary reuse, testability, or meaningfully reduced duplication.

## Preserve Responsibility and Domain Boundaries

Each class and module MUST have a clear, cohesive responsibility and belong to the domain that owns that behavior.

Keep domain-specific rules with their owning domain. A workflow may coordinate multiple domains when that is its purpose, but the coordination MUST be explicit and live at the appropriate application boundary. Do not move domain logic into unrelated domains or create unnecessary cross-domain dependencies.

## Keep Functions Focused and Compact

You MUST keep functions focused on a clear purpose and compact enough to understand in one pass.

Split a function when doing so clarifies distinct responsibilities or makes the main workflow easier to follow. Do not split mechanically by line count, or create tiny helpers that only move code around and make the flow harder to trace.

## Keep Files Manageable

When a file becomes excessively large or difficult to navigate, you MUST split it into cohesive, clearly named files while preserving responsibility and domain boundaries.

Split by responsibility and domain, not by arbitrary line counts. Do not fragment cohesive code or introduce extra indirection merely to make files shorter.

## Write for Human Understanding

You MUST use clear names, straightforward control flow, and familiar patterns. Do not use cleverness or excessive compression at the expense of readability.

Make the intent easy to understand for someone reviewing or maintaining the code. Remove duplication and unnecessary structure, but keep boundaries that make the code clearer.

## Quality Rules

Adapted from the Quality Rules of antirez's DwarfStar (`ds4`): https://github.com/antirez/ds4/blob/main/AGENT.md

- Keep the implementation small, sharp and easy to understand. Write elegant code. Do not settle for the first thing that comes to mind: look for the most minimal design that works better.
- Do not introduce slop: fragile code that patches specific cases, dead code, useless code, or code far more complicated than it should be.
- Preserve correctness before convenience or speed. Do not keep a shortcut that makes a number on screen drift from what the data says.
- Comment beside the implementation where the reason is not obvious from the local code: units, time zones, day boundaries, source precedence, vendor quirks. Prefer these comments over separate design documents. Keep them instructive and compact: explain why, not what.
- Keep public APIs narrow. The viewer does not know vendor formats; importers do not know about charts.
- Do not add permanent semantic variants behind flags or settings: each metric has one documented method of computation. Privacy switches (`--offline`, `--lan`) and the user's source priority are not semantic variants.

## open-health-archive constraints

A vendor-neutral archive of personal health data (CSV and GPX files in a folder the user owns, typically synced to Google Drive), the importers that write it and a local viewer that reads it. Two parts: `schema/` (the archive contract and synthetic fixtures) and `viewer/` (Python package `healthviz`: the importers for Health Connect's daily export and Xiaomi, and the Streamlit viewer).

- The archive schema in `schema/` is the only contract between writers and the viewer. Version it, document every column with its unit, and change it only together with its fixtures and every writer and reader. Writers never apply cross-device priority. Only explicitly flagged vendor resting HR and same-source missing-metric fallback summaries may be precomputed; the viewer computes other summaries and resolves sources at read time.
- Never commit, log, print or put in fixtures real health data, account or device identifiers (Xiaomi `Uid`, `Sid`, `Did`, `Identifier`, `Alias`), GPS coordinates or profile data. Fixtures are synthetic. Errors reference `file:row` and a reason, never values. Real exports are only read locally by the maintainer, never in CI.
- Missing data is never zero. Keep empty fields for unknown values, mark incomplete days and keep them out of daily averages, records and observations. Point readings such as weight and SpO₂ count on any day, worn or not. Never invent sleep stages or readings, and never sum two sources for the same interval.
- The viewer is reachable only from the host's loopback by default: native execution binds to `127.0.0.1`; Docker execution binds inside the container to `0.0.0.0` and publishes only `127.0.0.1:8501:8501`. Disable Streamlit usage statistics in code. LAN exposure requires an explicit user choice; `--lan` alone must not change Docker's host port binding. The only outbound requests are OpenStreetMap tiles, disabled by `--offline`, and track downloads during a Xiaomi import. No telemetry, accounts, servers, Google APIs or databases beyond in-process DuckDB.
- Personal settings (profile, priorities, thresholds) live in the user's config file, never in the archive or the repository.
- Observations are descriptive and relative to the user's own baseline. No scores, diagnoses or medical advice.
- Run Python development, tests, imports and the viewer in Docker. Do not install Python, uv or project dependencies on the host. Keep Python 3.12+ and uv inside the container, with a committed `viewer/uv.lock`. Add a dependency only when the standard library or an existing dependency (Streamlit, Plotly, pydeck, DuckDB) cannot reasonably do the job. Pin versions deliberately.
- Tests are deterministic and offline: no real exports, no network (fake the track download), temporary directories only. Every behavior change comes with a test.
- Never report a test, build or check as passing unless it was run and its output checked. Never describe behavior as private or secure without a test or review that verifies it.
- Work on a dedicated feature branch with logically scoped, one-line conventional commits, without Co-Authored-By trailers. Never commit planning documents (design specs, implementation plans) or reference them from tracked files.
- Never push, create public repositories, publish releases or publish packages without the maintainer's explicit authorization.
- Code, comments, docs, commits and UI are in English; the UI uses metric units, ISO dates, ISO weeks and a 24-hour clock.
- Docker must not receive privileged mode, the Docker socket, the user's home directory or unrelated host directories. Keep real data out of the image and build context via `.dockerignore`. Run as a non-root user. Mount original exports and tracks read-only; mount the normalized archive read-only in the viewer and writable only during import. Keep personal configuration in a separate mounted directory. Tests mount no personal data.
- Before committing Python changes, run ruff formatting, lint and pytest in the development container, with `/workspace/viewer` as its working directory. After syncing locked dependencies, run tests with `--network none` and `uv run --no-sync`: `ruff format --check .`, `ruff check .` and `pytest`.
