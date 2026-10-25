# syntax=docker/dockerfile:1

# Base image pinned by digest; Dependabot proposes digest bumps weekly.
ARG PYTHON_IMAGE=python:3.13-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

# ---- build: install hash-verified dependencies into an isolated venv ----
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /opt/venv
COPY requirements.lock ./
RUN /opt/venv/bin/pip install --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps .

# ---- runtime: no build tooling, no shell-level package installs, non-root ----
FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="healthqueue-api" \
      org.opencontainers.image.description="HealthQueue appointment scheduling API" \
      org.opencontainers.image.source="https://github.com/martineh4/healthqueue-platform" \
      org.opencontainers.image.version="${VERSION}"
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
USER 10001:10001
EXPOSE 8000
# Our middleware emits structured access logs, so uvicorn's own are disabled.
CMD ["uvicorn", "healthqueue.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
