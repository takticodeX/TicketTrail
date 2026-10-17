# TicketTrail – Technical Specification

Oct 15, 2026 · @Kayser

## 1. Overview

TicketTrail is a Dockerized, multi-user web app. It reads commits from any Git repository and posts each commit message as a comment on the Azure DevOps work item the message references.

**Goals**

- Each user manages their own **projects**. A project pairs one Git connection with one Azure DevOps board.
- Git access works with any HTTPS Git host: Azure Repos (the first target), GitHub, GitLab, Bitbucket, Gitea and self-hosted servers.
- Ticket references are found with a regex pattern set per project. The default is `AB#(\d+)`.
- A sync can run on demand ("Sync now") or on a schedule set per project.
- A commit is never posted twice to the same work item, even if the sync is retried or run again.
- All credentials are entered by the user on a Settings page and stored encrypted.

**Out of scope for v1**

- Webhooks and push-triggered syncs. The design should still leave room to add them later.
- SSH Git access. Only HTTPS with a token or password is supported.
- Changing work item state (for example, closing a ticket from the commit).
- Work-item systems other than Azure DevOps. The integration layer is still built behind an interface so others can be added.
- SSO and OIDC login.

## 2. Instructions for the AI agent

Build TicketTrail **one milestone at a time** (section 12). Stop at every milestone gate and wait for explicit human approval before going on.

1. At the start of each milestone, restate its scope in 3–5 lines. Ask about anything that is ambiguous before you write any code.
2. Implement only what the current milestone covers. Don't scaffold features from later milestones beyond simple stubs.
3. Keep the app runnable with `docker compose up` at the end of every milestone.
4. Write tests together with the code, not after it. The milestone's tests must pass before you report it as done.
5. Close each milestone with a report:
   - what was built
   - how to verify it (exact commands and the steps to click through)
   - test results
   - known limitations and open questions
6. End the report with: **"Milestone N complete. Approve to start Milestone N+1?"** Then stop and wait.
7. If the spec conflicts with reality (an API behaves differently, a library is missing), stop and report it. Don't silently change the design.
8. Never commit real secrets. Use `.env.example` with placeholder values.
9. Use conventional commits (`feat:`, `fix:`, `test:`, `docs:`) and one branch per milestone (`milestone/2-auth`).

## 3. Architecture and tech stack

The app runs as six containers, started together with Docker Compose. The API and the worker are built from the same Python codebase. The worker runs the scheduled and manual syncs, so the API is never blocked by a long sync.

&#91;embedded content: TicketTrail architecture · 6 compose services, 3 external systems\]

Requests flow left to right. The API only stores settings and queues work; the worker alone talks to Git hosts and Azure DevOps.

| Service | Image / tech | Role |
| --- | --- | --- |
| `frontend` | React 18 + Vite + TypeScript, served by Nginx | Single-page app. Nginx also proxies `/api` to the backend |
| `api` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 | REST API, authentication, settings, starts sync runs |
| `worker` | Same image as `api`, runs Celery | Runs sync jobs: Git fetch, parsing, posting to Azure |
| `scheduler` | Same image, runs Celery Beat (database-backed schedule) | Starts scheduled syncs on each project's cron |
| `db` | PostgreSQL 16 | All persistent data |
| `redis` | Redis 7 | Celery broker and per-project sync locks |

**Libraries**

- **Git:** run the `git` CLI through GitPython; `git` is installed in the image. Don't use host-specific APIs; reading commits only needs plain Git.
- **Azure DevOps:** `httpx` against the REST API directly, wrapped in a client class. Avoid the heavyweight Azure SDK.
- **Secrets:** `cryptography` (Fernet). The key comes from the environment variable `TT_ENCRYPTION_KEY`.
- **Auth:** `argon2-cffi` for password hashing and `PyJWT` for access and refresh tokens.
- **Scheduling:** `celery-redbeat` or `sqlalchemy-celery-beat`, so schedules can be changed at runtime from the UI.
- **Frontend:** React Router, TanStack Query, React Hook Form + Zod, and Mantine as the UI component library.
- **Testing:** pytest, `respx` to mock httpx, testcontainers for Postgres, Vitest and Playwright for the frontend.

Repository volumes: each project's repo is cloned as a bare/mirror clone into the volume `repos_data` at `/data/repos/<project_id>`. Later syncs only `git fetch`.

## 4. Data model

Every user-owned row carries `owner_id`, and every query filters on it. Connections are reusable: one Azure connection can serve several projects. All tables use UUID primary keys and `created_at` / `updated_at` timestamps.

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `email` (unique), `password_hash`, `display_name`, timezone (IANA, default UTC), `role` (`user` \| `admin`), `is_active` | The first registered user becomes `admin` |
| `git_connections` | `owner_id`, `name`, `repo_url`, `auth_type` (`token` \| `basic` \| `none`), `username`, `secret_enc`, commit\_url\_template (nullable), `last_test_at`, `last_test_ok` | `secret_enc` = Fernet-encrypted token or password |
| `azure_connections` | `owner_id`, `name`, `organization_url` (e.g. `https://dev.azure.com/acme`), `azure_project`, `pat_enc`, `last_test_at`, `last_test_ok` | PAT needs the *Work Items (Read & Write)* scope |
| `projects` | `owner_id`, `name`, `git_connection_id`, `azure_connection_id`, `branches` (text\[\]; empty = default branch only), `ticket_pattern` (default `AB#(\d+)`), `comment_template`, `start_from` (date or SHA), `include_merge_commits` (bool, default false), `schedule_cron` (nullable), `schedule_enabled`, `dry_run_default` | One repo → one board |
| `sync_runs` | `project_id`, `trigger` (`manual` \| `scheduled`), `dry_run`, `status` (`queued` \| `running` \| `success` \| `partial` \| `failed` \| skipped), `started_at`, `finished_at`, `commits_scanned`, `comments_posted`, `skipped`, `errors`, `error_message` | One row per sync run |
| `sync_run_items` | `sync_run_id`, `commit_sha`, `work_item_id`, `action` (`posted` \| `would_post` \| `skipped_duplicate` \| `skipped_not_found` \| `no_reference` \| `error`), `detail` | The audit trail shown in the UI |
| `posted_comments` | `project_id`, `commit_sha`, `work_item_id`, `azure_comment_id`, status (pending \| posted), `posted_at` | **Unique (`project_id`, `commit_sha`, `work_item_id`)**: this is what guarantees a commit is never posted twice |
| `project_cursors` | `project_id`, `branch`, `last_sha` | Where the last successful sync stopped on each branch |
| `refresh_tokens` | `user_id`, `token_hash`, `expires_at`, `revoked` | Lets sessions be revoked |

`posted_comments` is the source of truth for de-duplication. `project_cursors` is only an optimization so the app doesn't rescan the whole history. If the cursors are deleted, a full rescan still posts nothing twice.

## 5. Git integration and ticket parsing

TicketTrail talks to Git through plain Git over HTTPS, so any host works. Code specific to a host is limited to suggesting a default username in the UI.

**Authentication**

- Credentials are never written into the remote URL, `.git/config` or logs.
- They are passed per command with `git -c http.extraHeader="Authorization: Basic <base64(user:secret)>"`. Alternatively, use a temporary `GIT_ASKPASS` script that reads them from environment variables.
- Default usernames suggested in the UI:

| Host | Username | Secret |
| --- | --- | --- |
| Azure Repos | any non-empty value (e.g. `pat`) | PAT with *Code (Read)* scope |
| GitHub | `x-access-token` or the account name | Fine-grained or classic PAT with read access to contents |
| GitLab | `oauth2` | Personal/project access token with `read_repository` |
| Bitbucket Cloud | account username or `x-token-auth` | App password or access token |
| Generic / self-hosted | as configured | Password or token |

**Reading commits**

1. First sync: `git clone --mirror` into `/data/repos/<project_id>`. Later syncs: `git fetch --prune`.
2. Resolve the branches: the configured list, or the remote's default branch (`HEAD`) if the list is empty.
3. For each branch, list the commits from the cursor to the branch tip, oldest first: `git log --reverse --format=<NUL-separated fields> <cursor>..<branch>`. With no cursor, start from `start_from` if it is set; otherwise list the full history.
4. Fields per commit: SHA, author name and email, author date, committer date, subject, full body, and the number of parents.
5. Skip merge commits (more than one parent) unless `include_merge_commits` is set.
6. A commit reachable from several branches is processed once per run (deduplicated by SHA).
7. If the cursor commit no longer exists (history was rewritten by a force-push), log a warning, fall back to `start_from` or the full history, and rely on `posted_comments` to avoid duplicates.
8. Set a time limit on every Git command (default 300 s, set with `TT_GIT_TIMEOUT`).

**Ticket pattern**

- A Python regex set per project. The default is `AB#(\d+)`, which matches Azure Boards' own commit-linking convention.
- The pattern must contain exactly one capture group, or a named group `(?P<id>…)`, that captures digits only. The API validates this when the pattern is saved and rejects anything else.
- Run patterns with the `regex` package and a timeout (e.g. 100 ms per message) to guard against catastrophic backtracking.
- Matching is case-insensitive by default. Search the whole message, subject and body.
- One commit can reference several work items. Post one comment per unique ID.
- The Settings page has a **pattern tester**: paste sample commit messages and see the IDs that are extracted.

Examples: `AB#(\d+)` (default), `#(\d+)`, `(?:fixes|refs)\s+#(\d+)`, `PROJ-(\d+)`.

## 6. Azure DevOps integration

TicketTrail calls the Azure DevOps REST API with a PAT, using the header `Authorization: Basic base64(":" + PAT)`. The PAT needs **Work Items (Read & Write)** (`vso.work_write`). All calls go through one `AzureBoardsClient` class, which sits behind a `WorkItemTracker` interface so other trackers can be added later.

| Purpose | Call |
| --- | --- |
| Test connection | `GET {org_url}/_apis/projects/{project}?api-version=7.1` |
| Check work items exist (batched, up to 200 IDs) | `GET {org_url}/{project}/_apis/wit/workitems?ids=1,2,3&fields=System.Id,System.Title,System.WorkItemType&errorPolicy=omit&api-version=7.1` |
| Add comment | `POST {org_url}/{project}/_apis/wit/workItems/{id}/comments?format=markdown&api-version=7.1-preview.4`, body `{"text": "…"}` |
| Read comments (only to recover after a crash) | `GET {org_url}/{project}/_apis/wit/workItems/{id}/comments?api-version=7.1-preview.4` |

Reference: [Comments – Add Work Item Comment](https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/comments/add-work-item-comment?view=azure-devops-rest-7.1). The comments API is still marked *preview*, so keep the `api-version` in one constant.

**Comment template**

The template is Markdown and can be edited per project. Default:

```markdown
**Commit** [`{short_sha}`]({commit_url}) on `{branch}` by {author_name}, {author_date}

{message}

<sub>Posted by TicketTrail · tt:{sha}</sub>
```

- Available variables: `{sha}`, `{short_sha}`, `{message}`, `{subject}`, `{body}`, `{author_name}`, `{author_email}`, `{author_date}`, `{branch}`, `{repo_name}`, `{commit_url}`.
- `{commit_url}` comes from `commit_url_template` on the Git connection. If that is empty, it is inferred for known hosts:
  - Azure Repos and GitHub: `…/commit/{sha}`
  - GitLab: `…/-/commit/{sha}`
  - Bitbucket: `…/commits/{sha}`
  - Unknown hosts: an empty string, and the link is dropped.
- The `tt:{sha}` marker is always appended, even if the user removes it from their template. Crash recovery depends on it.
- Escape the commit message so Markdown in it can't break the layout. Truncate it to 10,000 characters.

**Errors and limits**

- **401/403:** mark the connection as failing and stop the run. Report "PAT invalid, expired or missing scope".
- **404 / work item missing:** record the item as `skipped_not_found` and continue with the rest.
- **429 or 503:** honor `Retry-After`. Otherwise use exponential backoff with jitter (1 s, 2 s, 4 s … up to 60 s, at most 5 attempts).
- Also honor Azure's `X-RateLimit-Delay` / `Retry-After` throttling headers.
- Make at most 5 concurrent requests per Azure organization, across all workers.

## 7. Sync engine

A sync run is one Celery task, `sync_project(project_id, trigger, dry_run)`. A run is safe to repeat at any point: running it twice, or after a crash, never produces a duplicate comment.

**Triggers**

- **Manual:** the "Sync now" button calls `POST /api/projects/{id}/sync`. The API creates a `sync_runs` row with status `queued`, sends the task to Celery, and returns the run ID straight away.
- **Scheduled:** each project has an optional 5-field cron expression (`schedule_cron`) and a switch (`schedule_enabled`). The scheduler reads them from the database, so changes in the UI take effect without a restart.
  - The minimum interval is 5 minutes, set with `TT_MIN_SCHEDULE_MINUTES`.
  - Cron is evaluated in the user's time zone, which is stored on the user's profile and defaults to UTC.
- **Dry run:** a run with `dry_run=true` does every step except posting. Items are recorded as `would_post`, and no cursors are moved.

**One run, step by step**

1. Take a Redis lock `tt:sync:<project_id>` with a 30-minute time-to-live. If the lock is already held, mark the new run `skipped` and stop. Only one run per project at a time.
2. Set the run to `running`. Decrypt the credentials in memory only.
3. Fetch the repo and list the new commits (section 5).
4. Extract the work item IDs from each commit. Commits with no match are recorded as `no_reference`.
5. Remove pairs that are already in `posted_comments` with status `posted`. Record them as `skipped_duplicate`.
6. Check that the remaining IDs exist, in batches. Missing IDs are recorded as `skipped_not_found`.
7. For each pair (commit, work item), oldest commit first:
   1. Insert a `posted_comments` row with status `pending`. The unique constraint stops a parallel duplicate here.
   2. Post the comment to Azure.
   3. Update the row to `posted`, store the `azure_comment_id`, and record the item as `posted`.
8. Move each branch cursor forward only past commits whose pairs all succeeded or were skipped for good. If anything failed with an error that may go away, leave the cursor where it is so the next run retries it.
9. Finish the run with status `success`, `partial` (some errors) or `failed`, and store the counters. Release the lock.

**Crash recovery**

If a run finds a `pending` row left behind by an earlier crash, it reads that work item's comments in Azure and looks for the `tt:{sha}` marker.

- Marker found: mark the row `posted` and don't post again.
- Marker not found: post the comment.

## 8. REST API contract

The API is JSON under `/api/v1`, with OpenAPI docs at `/api/docs`. Every endpoint except auth and health needs `Authorization: Bearer <access token>`. Resources owned by someone else return **404**, not 403, so their IDs don't leak. Secrets are write-only: responses return `"has_secret": true` and never the value.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/register` | Create an account. Can be turned off with `TT_ALLOW_REGISTRATION=false` |
| POST | `/auth/login` | Returns an access token (15 min) and a refresh token (7 days, httpOnly cookie) |
| POST | `/auth/refresh` · `/auth/logout` | Rotate or revoke the refresh token |
| GET / PATCH | `/me` | Profile: name, time zone, password change |
| GET / POST | `/git-connections` | List / create |
| GET / PATCH / DELETE | `/git-connections/{id}` | Read / update / delete. Delete is refused while a project uses the connection |
| POST | `/git-connections/{id}/test` | Runs `git ls-remote`, returns `{ok, branches[], default_branch, error}` |
| GET / POST | `/azure-connections` | List / create |
| GET / PATCH / DELETE | `/azure-connections/{id}` | Read / update / delete |
| POST | `/azure-connections/{id}/test` | Returns `{ok, project_name, error}` |
| GET / POST | `/projects` | List / create |
| GET / PATCH / DELETE | `/projects/{id}` | Read / update / delete |
| POST | `/projects/{id}/test-pattern` | Body `{pattern, samples[]}`, returns the IDs found in each sample |
| POST | `/projects/{id}/sync` | Body `{dry_run: bool}`. Returns `202` with `{run_id}` |
| GET | `/projects/{id}/runs` | Paginated run history |
| GET | `/runs/{run_id}` | Run detail with counters |
| GET | `/runs/{run_id}/items` | Paginated items, filterable by `action` |
| POST | `/runs/{run_id}/cancel` | Cooperative cancel: the worker checks a flag between commits |
| GET | `/admin/users` · PATCH `/admin/users/{id}` | Admin only: list users, turn accounts on or off |
| GET | `/health` · `/ready` | Liveness / readiness (database, Redis) |

Errors use one shape: `{"error": {"code": "string", "message": "human readable", "details": {}}}`. List endpoints take `?page=&page_size=` (default 25, max 100).

## 9. Frontend pages

The UI is a responsive single-page app with light and dark themes. Everything a user configures lives under **Settings**. The main page is the **Dashboard**.

| Page | Route | Contents |
| --- | --- | --- |
| Login / Register | `/login`, `/register` | Email + password. Register is hidden when registration is turned off |
| Dashboard | `/` | One card per project: last run status and time, next scheduled run, comments posted, and **Sync now** / **Dry run** buttons |
| Project detail | `/projects/:id` | Run history table. Click a run to open its item list (commit SHA, message subject, work item ID with a link to Azure, action, detail), with filters by action |
| Settings → Git connections | `/settings/git` | List plus a form: name, repo URL, auth type, username (prefilled for the detected host), token or password, commit URL template, **Test connection** (shows the branches found) |
| Settings → Azure connections | `/settings/azure` | List plus a form: name, organization URL, project, PAT, **Test connection** |
| Settings → Projects | `/settings/projects` | Wizard: pick a Git connection → branches → pick an Azure connection → ticket pattern with **live pattern tester** → comment template with **live preview** → start point → schedule |
| Settings → Profile | `/settings/profile` | Display name, time zone, change password |
| Admin → Users | `/admin/users` | Admins only: list users, turn accounts on or off |

**UI rules**

- Secret fields show `••••••• (saved)` once saved. Typing a new value replaces the secret; leaving the field empty keeps it.
- The schedule field offers presets (every 15 min, hourly, daily at 08:00, weekdays at 08:00) plus a custom cron. It shows the next three run times in plain language.
- The run detail page polls every 2 s while the run is `queued` or `running`.
- Every destructive action asks for confirmation.
- All forms validate on the client with Zod, using the same rules as the API (pattern rules, URL format, cron syntax).

## 10. Security

TicketTrail stores other systems' credentials, so the security rules below are requirements, not nice-to-haves.

- **Secrets at rest:** Fernet-encrypt every token, PAT and password with `TT_ENCRYPTION_KEY`. Support key rotation with `TT_ENCRYPTION_KEY_OLD` and a `manage.py rotate-keys` command.
- **Secrets in transit and in logs:** never return secrets from the API or log them. A logging filter scrubs `Authorization` headers, URLs with credentials in them, and known secret fields. Git error output is cleaned before it is stored in `sync_run_items.detail`.
- **Tenant isolation:** every repository-layer query goes through an owner filter. Add tests where user B tries to read, change, sync and test user A's resources.
- **Passwords:** Argon2id hashing, at least 10 characters, and login rate limits (5 attempts a minute per IP and per email).
- **Tokens:** JWT access tokens signed with HS256 using `TT_JWT_SECRET`. Refresh tokens are httpOnly, Secure and SameSite=Strict, stored hashed, and rotated each time they are used.
- **SSRF guard:** repo and Azure URLs must be `https://`. Block private, loopback and link-local addresses unless `TT_ALLOW_PRIVATE_HOSTS=true` (needed for self-hosted Git on the LAN).
- **Containers:** run as a non-root user, mount the filesystem read-only except `/data`, and add healthchecks.
- **Web:** strict CORS (same origin via the Nginx proxy), security headers (CSP, HSTS when served over TLS), and CSRF protection on the refresh endpoint.
- **Least privilege guidance:** the UI tells users which minimum scopes their PATs need: *Code (Read)* for Git and *Work Items (Read & Write)* for Azure.

## 11. Repository layout and configuration

Everything lives in one monorepo, with the backend and frontend as separate Docker build contexts.

```text
tickettrail/
├── docker-compose.yml          # production-like stack
├── docker-compose.dev.yml      # hot reload, exposed ports
├── .env.example
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py             # FastAPI app factory
│       ├── config.py           # pydantic-settings, TT_* env vars
│       ├── db/                 # models, session, repositories (owner-scoped)
│       ├── api/v1/             # routers: auth, me, git, azure, projects, runs, admin
│       ├── core/               # security, crypto, logging, errors
│       ├── integrations/
│       │   ├── git/            # GitClient, host detection, URL builders
│       │   └── trackers/       # WorkItemTracker interface, AzureBoardsClient
│       ├── sync/               # parser, template renderer, engine, locks
│       └── worker/             # celery app, tasks, beat schedule loader
│   └── tests/                  # unit/, integration/, fixtures/ (sample repos)
└── frontend/
    ├── Dockerfile              # build stage + nginx stage
    ├── nginx.conf
    └── src/                    # pages/, components/, api/, hooks/, schemas/
```

**Environment variables** (all prefixed `TT_`, documented in `.env.example`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `TT_DATABASE_URL` | `postgresql+psycopg://tt:tt@db:5432/tickettrail` | Database connection |
| `TT_REDIS_URL` | `redis://redis:6379/0` | Broker and locks |
| `TT_ENCRYPTION_KEY` | *(required)* | Fernet key for secrets |
| `TT_JWT_SECRET` | *(required)* | Signs JWTs |
| `TT_ALLOW_REGISTRATION` | `true` | Public sign-up on or off |
| `TT_ALLOW_PRIVATE_HOSTS` | `false` | SSRF guard exception |
| `TT_GIT_TIMEOUT` | `300` | Seconds per Git command |
| `TT_MIN_SCHEDULE_MINUTES` | `5` | Shortest schedule interval allowed |
| `TT_AZURE_MAX_CONCURRENCY` | `5` | Concurrent requests per Azure organization |
| `TT_LOG_LEVEL` | `INFO` | Logging level; logs are JSON |
| `TT_PUBLIC_URL` | `http://localhost:8080` | Used in links and cookies |

Volumes: `pg_data` (database) and `repos_data` (Git mirrors). Only `frontend` publishes a port (8080 by default). TLS is expected from a reverse proxy in front of the stack.

## 12. Milestones

**M1 (foundation and decisions) is complete once this spec is approved.** The agent builds M2 through M7 in order. Each milestone ends at a gate: the agent stops and waits for human approval (section 2).

**M2 – Skeleton, Docker and multi-user auth**

- *Build:*
  - Monorepo layout, both Dockerfiles, `docker-compose.yml` and the dev compose file.
  - Config loading, the database with Alembic and the base models (`users`, `refresh_tokens`).
  - Auth endpoints, `/me` and `/health`.
  - Frontend shell with routing, the login and register pages, the auth guard, and an empty dashboard.
- *Accept when:*
  - `docker compose up` on a clean machine serves the app at `:8080`.
  - Two users can register and log in. The first one is admin.
  - Expired access tokens refresh silently.
  - Auth tests pass.

**M3 – Settings: connections and projects**

- *Build:*
  - The `git_connections`, `azure_connections` and `projects` models.
  - Encryption of secrets.
  - CRUD endpoints, the test endpoints (`git ls-remote` and the Azure project lookup), and the pattern tester.
  - All the Settings pages, including the project wizard, the template preview and the schedule field (stored, not run yet).
- *Accept when:*
  - A user can create, edit, test and delete Git connections, Azure connections and projects against a real Azure Repos repo and board.
  - Secrets are never returned by the API.
  - User B gets 404 on all of user A's resources.
  - The database holds only encrypted secret values.

**M4 – Git ingestion engine and dry run**

- *Build:*
  - `GitClient` (mirror clone and fetch, commit listing, cursors, force-push fallback).
  - The ticket parser with the regex timeout.
  - `sync_runs` and `sync_run_items`, the Celery worker, and `POST /sync` with `dry_run=true`.
  - The project detail page with run history and the item list.
- *Accept when:*
  - A dry run on the real repo lists each commit with its extracted IDs.
  - Merge commits are skipped by default.
  - Commits with no reference are labelled.
  - Nothing is posted to Azure.
  - The parser and Git tests pass against fixture repos built in the tests, including a force-push case.

**M5 – Azure posting and de-duplication**

- *Build:*
  - `AzureBoardsClient` (existence check, add comment, list comments), the template renderer, and `posted_comments` with the pending/posted protocol and crash recovery.
  - Backoff, rate limiting and error classification.
- *Accept when:*
  - A real sync posts one comment per commit/work item pair, formatted from the template.
  - Running the sync again posts nothing new.
  - Killing the worker in the middle of a run and re-running it creates no duplicates (integration test with Azure mocked).
  - 401, 404 and 429 are handled as described in section 6.

**M6 – Scheduling and orchestration polish**

- *Build:*
  - The database-backed beat scheduler, schedule switch, time-zone handling and minimum interval.
  - The per-project Redis lock, cancel endpoint and dashboard cards with the next run time.
  - Live polling of runs in progress.
- *Accept when:*
  - A project scheduled every 5 minutes runs by itself.
  - Changing or turning off the schedule in the UI takes effect without a restart.
  - Overlapping runs are skipped.
  - A run can be cancelled.

**M7 – Hardening and handover**

- *Build:*
  - Everything in section 10 that isn't in place yet: log scrubbing, rate limits, SSRF guard, headers, non-root containers, key rotation.
  - Admin users page.
  - A Playwright end-to-end test of the main path.
  - CI workflow (lint, type-check, tests, image build).
  - README covering setup, PAT scopes per Git host, backups and upgrades.
- *Accept when:*
  - CI is green.
  - Following the README alone, a person deploys a fresh instance and completes a real sync.
  - A secret-leak test (search logs and the database for plaintext tokens) finds nothing.

## 13. Testing and definition of done

A milestone is done only when its acceptance criteria are met, its tests pass in CI, and the human has approved it at the gate.

**Test layers**

- **Unit:**
  - parser (patterns, multiple IDs, timeout, invalid patterns)
  - template renderer (escaping, marker always present)
  - URL builders and host detection
  - crypto round-trip
  - cron validation
- **Integration:**
  - API against a real Postgres (testcontainers)
  - the sync engine against fixture Git repos created in temp directories
  - Azure mocked with `respx`, covering 200, 401, 404, 429 with `Retry-After`, and timeouts
- **Idempotency suite:**
  - run a sync twice
  - crash after the POST and before the database update
  - two workers on the same project at once
  - a force-pushed branch
  - each case asserts exactly one comment per pair
- **Isolation suite:** for every endpoint, check that a second user gets 404 on the first user's resources.
- **End to end (Playwright):** register → create both connections → create a project → dry run → real sync (Azure mocked) → see the history.

**Quality bar**

- Backend: `ruff` + `mypy --strict` on `app/`, coverage ≥ 80% on `sync/` and `integrations/`.
- Frontend: `eslint` + `tsc --noEmit`, with no `any` in the API layer.
- Every endpoint has typed Pydantic schemas and appears correctly in OpenAPI.
- No `TODO` left without an issue reference in the final milestone.
