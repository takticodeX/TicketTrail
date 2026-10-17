# TicketTrail

TicketTrail reads commits from a Git repository and posts each commit message as a comment
on the Azure DevOps work item it references. See [SPEC.md](SPEC.md) for the full design.

> Status: Milestone 3. Accounts, Git and Azure DevOps connections (with connection tests)
> and projects can be set up under **Settings**. Syncing arrives in Milestones 4–6. A full
> setup and operations guide is part of Milestone 7.

Connection tests run on the worker and refuse hosts on private networks. To use a Git
server on your LAN, set `TT_ALLOW_PRIVATE_HOSTS=true` in `.env`.

## Run it

You need Docker with Compose v2, or Podman 5 with `podman compose`.

```sh
cp .env.example .env
# Generate the two required secrets and paste them into .env:
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # TT_ENCRYPTION_KEY
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # TT_JWT_SECRET

docker compose up -d --build        # or: podman compose up -d --build
```

Open <http://localhost:8080>. The first account you register becomes the administrator.
If port 8080 is taken, set `TT_HTTP_PORT` and `TT_PUBLIC_URL` in `.env`.

The API docs are at <http://localhost:8080/api/docs>.

## Develop

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

This runs the API with auto-reload (also on `127.0.0.1:8000`) and the Vite dev server on
port 8080, and exposes Postgres and Redis on localhost.

### Backend tests

Python 3.12 and [uv](https://docs.astral.sh/uv/). Integration tests start Postgres with
testcontainers, so Docker or Podman must be running.

```sh
cd backend
uv sync
uv run pytest                 # all tests
uv run pytest tests/unit      # no container runtime needed
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

To use an existing database instead of a container, set `TT_TEST_DATABASE_URL`.

After changing dependencies in `pyproject.toml`, refresh the pinned list the image installs:

```sh
uv export --no-dev --no-emit-project --format requirements-txt -o requirements.lock
```

### Frontend tests

Node 20 or later.

```sh
cd frontend
npm ci
npm test
npm run lint && npm run typecheck
```

## Layout

| Path | What |
| --- | --- |
| `backend/app` | FastAPI app, models, Celery worker (`api`, `worker`, `scheduler` share one image) |
| `backend/alembic` | Database migrations, run automatically when the `api` container starts |
| `frontend/src` | React single-page app; Nginx serves it and proxies `/api` |
