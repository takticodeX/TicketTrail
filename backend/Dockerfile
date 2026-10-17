# One image for the api, worker and scheduler services.
FROM docker.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# git is needed by the sync worker (Milestone 4); curl is not, healthchecks use Python.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --user-group tt \
    && mkdir -p /data/repos \
    && chown -R tt:tt /data

WORKDIR /app

# Install pinned, hash-checked dependencies first so code changes don't invalidate this layer.
# Regenerate after changing pyproject.toml:
#   uv export --no-dev --no-emit-project --format requirements-txt -o requirements.lock
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

USER tt

EXPOSE 8000

CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
