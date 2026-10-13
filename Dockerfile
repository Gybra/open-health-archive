FROM ghcr.io/astral-sh/uv:0.12.24 AS uv
FROM python:3.12.12-slim AS tooling
COPY --from=uv /uv /usr/local/bin/uv
RUN useradd --create-home --uid 1000 healthviz && mkdir /opt/venv && chown healthviz /opt/venv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace/viewer
USER healthviz
FROM tooling AS dev
COPY --chown=healthviz viewer/pyproject.toml viewer/uv.lock /workspace/viewer/
COPY --chown=healthviz viewer/src /workspace/viewer/src
RUN uv sync --locked
CMD ["uv", "run", "--no-sync", "healthviz", "--help"]
