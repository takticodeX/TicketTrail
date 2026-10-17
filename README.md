# TicketTrail

TicketTrail reads the commits of a Git repository and posts each commit message as a
comment on the Azure DevOps work items it references (for example `Fix login AB#123`).
It runs as a small Docker Compose stack, supports several users, and never posts the same
commit twice to the same work item.

- Works with any Git host over HTTPS: Azure Repos, GitHub, GitLab, Bitbucket, Gitea and
  self-hosted servers.
- **Dry run** shows exactly what would be posted, **Sync now** posts it, and projects can
  sync on a schedule.
- Credentials are entered in the web UI and stored encrypted.

The design is described in [SPEC.md](SPEC.md).

## Contents

1. [Install](#1-install)
2. [First steps](#2-first-steps)
3. [Access tokens: minimum scopes per host](#3-access-tokens-minimum-scopes-per-host)
4. [Configuration](#4-configuration)
5. [Running behind HTTPS](#5-running-behind-https)
6. [Backups and restore](#6-backups-and-restore)
7. [Upgrades](#7-upgrades)
8. [Rotating the encryption key](#8-rotating-the-encryption-key)
9. [Security notes](#9-security-notes)
10. [Troubleshooting](#10-troubleshooting)
11. [Development](#11-development)

## 1. Install

You need a Linux, macOS or Windows machine with **Docker** (Compose v2) or **Podman 5**
(`podman compose`). Wherever this guide says `docker compose`, Podman users type
`podman compose`.

```sh
git clone <this repository> tickettrail
cd tickettrail
cp .env.example .env
```

Generate the two required secrets and paste them into `.env` as `TT_ENCRYPTION_KEY` and
`TT_JWT_SECRET`. Run this twice, once per secret (any machine with Python 3):

```sh
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Keep `.env` private and back it up (see [section 6](#6-backups-and-restore)): without
`TT_ENCRYPTION_KEY` the stored tokens can't be decrypted.

Start the stack:

```sh
docker compose up -d --build
docker compose ps        # wait until every service is "healthy"
```

Open <http://localhost:8080>. If port 8080 is taken, set `TT_HTTP_PORT` (and
`TT_PUBLIC_URL`) in `.env` and run `docker compose up -d` again.

The stack runs six containers: `frontend` (Nginx, the only published port), `api`,
`worker`, `scheduler`, `db` (PostgreSQL 16) and `redis`. Database migrations run
automatically when the `api` container starts.

## 2. First steps

1. **Create an account.** The first account registered becomes the **administrator**.
   To stop strangers from signing up afterwards, set `TT_ALLOW_REGISTRATION=false`.
2. **Settings → Azure connections → Add.** Enter the organization URL
   (`https://dev.azure.com/<organization>`), the project name and a personal access token
   (see [section 3](#3-access-tokens-minimum-scopes-per-host)). Click **Save and test**.
3. **Settings → Git connections → Add.** Paste the repository's HTTPS clone URL. The
   username is filled in for known hosts; enter a token with read access. **Save and test**
   lists the branches it found.
4. **Settings → Projects → New project.** The wizard asks for the repository, the branches
   (empty means the default branch), the board, the **ticket pattern** with a live tester,
   the **comment template** with a preview, the **start point** and an optional
   **schedule**.
   - The default pattern `AB#(\d+)` matches Azure Boards' own convention (`Fix login AB#123`).
   - Set a start point (a date or a commit) unless you want comments on the whole history.
5. **Open the project** (Dashboard or Settings → Projects → Open) and run a **Dry run**:
   it lists every commit with the work items it would comment on, and changes nothing.
6. Click **Sync now**. The confirmation shows how many comments the last dry run found.

Run pages update live while a run is in progress and can be cancelled. Finished runs can
be deleted from the history (one at a time, or every dry run with **Clear dry runs**);
this never causes a comment to be posted again.

**Schedules** are 5-field cron expressions evaluated in your time zone (Settings →
Profile), at most once every 5 minutes by default. Scheduled runs follow the project's
"Dry run by default" setting. Changes apply within a minute; no restart is needed.

**Administrators** see **Admin → Users**, where accounts can be turned off (which signs
the user out everywhere and stops their schedules) and on again.

## 3. Access tokens: minimum scopes per host

TicketTrail only needs to **read** the repository and to **write comments** on work items.
Give tokens nothing more.

| Purpose | Host | Username | Token and minimum scope |
| --- | --- | --- | --- |
| Post comments | Azure DevOps (Boards) | (none) | PAT with **Work Items: Read & Write** (`vso.work_write`) |
| Read commits | Azure Repos | any non-empty value, e.g. `pat` | PAT with **Code: Read** |
| Read commits | GitHub | `x-access-token` | Fine-grained token with **Contents: Read** on the repository (or a classic token with `repo` for private repositories) |
| Read commits | GitLab | `oauth2` | Personal or project access token with **`read_repository`** |
| Read commits | Bitbucket Cloud | `x-token-auth` (access token) or your username (app password) | Repository access token or app password with **Repositories: Read** |
| Read commits | Other / self-hosted | as your server expects | A token or password of an account that can read the repository |

Public repositories need no token: choose **Public** in the Git connection.

When a token expires, edit the connection and paste the new one. Leaving a secret field
empty keeps the saved value.

## 4. Configuration

All settings are environment variables in `.env` (see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `TT_ENCRYPTION_KEY` | *(required)* | Fernet key that encrypts every stored token, PAT and password |
| `TT_JWT_SECRET` | *(required)* | Signs the login tokens (at least 32 characters) |
| `TT_ENCRYPTION_KEY_OLD` | *(empty)* | The previous key during a key rotation ([section 8](#8-rotating-the-encryption-key)) |
| `TT_PUBLIC_URL` | `http://localhost:8080` | The address users open; cookies are marked Secure when it starts with `https://` |
| `TT_HTTP_PORT` | `8080` | Host port the web app is published on |
| `TT_ALLOW_REGISTRATION` | `true` | Whether anyone can create an account |
| `TT_ALLOW_PRIVATE_HOSTS` | `false` | Allow Git or Azure servers on private networks (see below) |
| `TT_GIT_TIMEOUT` | `300` | Seconds a single Git command may take |
| `TT_MIN_SCHEDULE_MINUTES` | `5` | Shortest allowed schedule interval |
| `TT_AZURE_MAX_CONCURRENCY` | `5` | Concurrent requests per Azure organization, across all workers |
| `TT_LOG_LEVEL` | `INFO` | Log level; logs are JSON and secrets are masked |
| `TT_DATABASE_URL` | `postgresql+psycopg://tt:tt@db:5432/tickettrail` | Database connection |
| `TT_REDIS_URL` | `redis://redis:6379/0` | Task queue, locks and login rate limits |

**Self-hosted Git on your network.** TicketTrail refuses to connect to private, loopback
and link-local addresses, so a stolen account can't use it to probe your network. To sync
from a Git server on your LAN, set `TT_ALLOW_PRIVATE_HOSTS=true`. If that server uses a
certificate from your own CA, mount the CA into the `worker` container and set
`GIT_SSL_CAINFO` (and `SSL_CERT_FILE` for an on-premises Azure DevOps Server) to its path.

After changing `.env`, apply it with `docker compose up -d`.

## 5. Running behind HTTPS

The stack serves plain HTTP on one port. Put a reverse proxy that terminates TLS in front
of it (Caddy, Traefik, Nginx, a cloud load balancer), and:

1. Forward all traffic to the `frontend` port (default 8080).
2. Send `X-Forwarded-Proto: https` and `X-Forwarded-For` (most proxies do by default).
3. Set `TT_PUBLIC_URL=https://tickettrail.example.com` in `.env` and run
   `docker compose up -d`.

With that, login cookies are marked `Secure` and the app sends
`Strict-Transport-Security`. Example for Caddy:

```
tickettrail.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

## 6. Backups and restore

What to back up:

| What | Where | Why |
| --- | --- | --- |
| `.env` | the project folder | `TT_ENCRYPTION_KEY` is needed to read the stored tokens |
| The database | volume `tickettrail_pg_data` | Users, connections, projects, run history, and which comments were posted |

The Git mirrors (volume `tickettrail_repos_data`) don't need a backup: they are cloned
again on the next sync.

**Back up** the database (it can stay running):

```sh
docker compose exec -T db pg_dump -U tt -d tickettrail -Fc > tickettrail-$(date +%F).dump
```

**Restore** into a fresh or existing stack (this replaces the data):

```sh
docker compose stop api worker scheduler
docker compose exec -T db pg_restore -U tt -d tickettrail --clean --if-exists < tickettrail-2026-10-17.dump
docker compose start api worker scheduler
```

Restore with the same `TT_ENCRYPTION_KEY` the backup was made with. The table
`posted_comments` is what stops TicketTrail from posting a comment twice, so always
restore the whole database, not individual tables.

## 7. Upgrades

1. Back up the database and `.env` ([section 6](#6-backups-and-restore)).
2. Get the new version: `git pull` (or check out the release tag).
3. Compare `.env.example` with your `.env` and add any new settings.
4. Rebuild and restart: `docker compose up -d --build`.

Database migrations run automatically when the `api` container starts; the worker and
the scheduler wait until it is healthy. A run that was in progress during the restart is
marked failed once it has shown no progress for 10 minutes (when the worker starts, or
when the project's next run begins). Start it again: nothing is posted twice.

To roll back, check out the previous version and restore the backup taken in step 1.

## 8. Rotating the encryption key

1. Generate a new key (command in [section 1](#1-install)).
2. In `.env`, move the current value of `TT_ENCRYPTION_KEY` to `TT_ENCRYPTION_KEY_OLD`,
   and put the new key in `TT_ENCRYPTION_KEY`.
3. `docker compose up -d` (secrets encrypted with either key keep working).
4. Re-encrypt everything with the new key:
   ```sh
   docker compose exec api python manage.py rotate-keys
   ```
5. Remove `TT_ENCRYPTION_KEY_OLD` from `.env` and run `docker compose up -d` again.

If `rotate-keys` reports connections it could not decrypt, enter their tokens again in
Settings.

To rotate `TT_JWT_SECRET`, change it and restart: everyone has to log in again.

## 9. Security notes

- Tokens, PATs and passwords are encrypted at rest (Fernet) and never returned by the API.
  Passwords are hashed with Argon2id.
- Every user only sees their own connections, projects and runs.
- Credentials are passed to Git through the environment, never in URLs, Git config or
  command lines. Logs are JSON and mask Authorization headers, credentials in URLs and
  secret fields.
- Logins are limited to 5 attempts a minute per IP address and per email. Refresh tokens
  are httpOnly, SameSite=Strict cookies, rotated on every use; reusing an old one signs
  the user out everywhere.
- The app containers run as non-root users with a read-only filesystem (only
  `/data/repos` and `/tmp` are writable).
- To check a running instance for leaked secrets, pass the tokens you entered to:
  ```sh
  sh scripts/secret-leak-check.sh <token> <pat> <password>
  ```
  It searches every container's logs and a database dump, and prints only whether
  something was found.

## 10. Troubleshooting

| Symptom | What to check |
| --- | --- |
| "Authentication failed" on a Git connection | The username for your host (table in [section 3](#3-access-tokens-minimum-scopes-per-host)) and that the token can read the repository |
| "PAT invalid, expired or missing scope" | The Azure PAT's expiry date and its **Work Items: Read & Write** scope; it must belong to the same organization |
| "Project … was not found in this organization" | The organization URL and the project name in the Azure connection |
| "…resolves to a private address" | The server is on a private network: see `TT_ALLOW_PRIVATE_HOSTS` in [section 4](#4-configuration) |
| A run stays "Queued" | `docker compose ps`: is the `worker` healthy? `docker compose logs worker` |
| A run was "Skipped" | Another run of the same project was in progress; only one runs at a time |
| Scheduled runs don't start | Is the `scheduler` healthy, and is the project's schedule switched on? Times follow your time zone in Settings → Profile |
| "Too many login attempts" | Wait a minute |

Logs: `docker compose logs -f api worker scheduler`.

## 11. Development

### Layout

| Path | What |
| --- | --- |
| `backend/app` | FastAPI app, models, sync engine and Celery tasks (`api`, `worker` and `scheduler` share one image) |
| `backend/alembic` | Database migrations |
| `backend/tests` | Unit and integration tests (Postgres and Redis through testcontainers) |
| `frontend/src` | React single-page app (Vite, Mantine, TanStack Query) |
| `frontend/e2e` | Playwright end-to-end test |
| `e2e/fixtures` | Offline Git server and fake Azure DevOps for the end-to-end test |

### Running with hot reload

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The API reloads on code changes (and is also on `127.0.0.1:8000`), the Vite dev server
serves the app on port 8080, and Postgres and Redis are exposed on localhost.

### Backend checks

Python 3.12 and [uv](https://docs.astral.sh/uv/). Integration tests start Postgres and
Redis with testcontainers, so Docker or Podman must be running.

```sh
cd backend
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                    # everything
uv run pytest tests/unit         # no containers needed
```

After changing dependencies in `pyproject.toml`, refresh the pinned list the image installs:

```sh
uv export --no-dev --no-emit-project --format requirements-txt -o requirements.lock
```

### Frontend checks

Node 20 or later.

```sh
cd frontend
npm ci
npm run lint && npm run typecheck && npm test
```

### End-to-end test

The e2e stack uses its own Compose project, port and volumes, so it never touches your
data. It adds an offline HTTPS Git server and a fake Azure DevOps (`e2e/fixtures`).

```sh
TT_HTTP_PORT=8091 docker compose -p tickettrail-e2e -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --wait
cd frontend && npx playwright install chromium && npm run test:e2e
cd .. && sh scripts/secret-leak-check.sh -p tickettrail-e2e e2e-azure-pat-canary e2e-password-123
docker compose -p tickettrail-e2e -f docker-compose.yml -f docker-compose.e2e.yml down -v
```

CI (`.github/workflows/ci.yml`) runs all of the above: lint, type checks, unit and
integration tests with coverage, the image build, the end-to-end test and the
secret-leak check.
