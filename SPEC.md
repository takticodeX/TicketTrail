# TicketTrail – Technical Specification

Oct 15, 2026 · @Kayser

## 1. Overview

TicketTrail is a Dockerized, multi-user web app. It reads commits from any Git repository and posts each commit message as a comment on the Azure DevOps work item the message references.

**Goals**

- Each user manages their own **projects**. A project pairs one Git connection with one Azure DevOps board.
- A project can be **shared** with other users as viewer or editor, or belong to an **organization** (a team) instead of a user (section 4, *Access rules*). An administrator can transfer personal projects to another owner, for example when a colleague leaves.
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
| `scheduler` | Same image, runs Celery Beat | Ticks once a minute; the tick starts every scheduled sync that came due (section 7) |
| `db` | PostgreSQL 16 | All persistent data |
| `redis` | Redis 7 | Celery broker and result backend, per-project sync locks, the Azure concurrency limit and login rate limits |

**Libraries**

- **Git:** run the `git` CLI through GitPython; `git` is installed in the image. Don't use host-specific APIs; reading commits only needs plain Git.
- **Azure DevOps:** `httpx` against the REST API directly, wrapped in a client class. Avoid the heavyweight Azure SDK.
- **Secrets:** `cryptography` (Fernet). The key comes from the environment variable `TT_ENCRYPTION_KEY`.
- **Auth:** `argon2-cffi` for password hashing and `PyJWT` for access and refresh tokens.
- **Scheduling:** plain Celery Beat runs one dispatcher task (`tickettrail.dispatch_schedules`) every minute. The dispatcher reads the schedules from the database and evaluates them with `croniter`, so schedules change at runtime from the UI without `celery-redbeat` or `sqlalchemy-celery-beat`.
- **Regex:** the `regex` package, for its per-match timeout.
- **Frontend:** React Router, TanStack Query, React Hook Form + Zod, and Mantine as the UI component library. `cron-parser` and `cronstrue` for the schedule field, `react-markdown` for the template preview.
- **Testing:** pytest, `respx` to mock httpx, testcontainers for Postgres and Redis, Vitest and Playwright for the frontend.

Repository volumes: each project's repo is kept as a bare, blobless clone of its branches (`git clone --bare --filter=blob:none`) in the volume `repos_data` at `/data/repos/<project_id>`. Later syncs only `git fetch`. A `--mirror` clone is not used: it also fetches every other ref, such as GitHub's `refs/pull/*`, which can be gigabytes.

## 4. Data model

Connections and projects belong to a user (`owner_id`) or to an organization (`organization_id`): exactly one of the two is set, enforced by a check constraint, and names are unique per owner. Connections are reusable: one Azure connection can serve several projects. All tables use UUID primary keys and `created_at` / `updated_at` timestamps.

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `email` (unique), `password_hash`, `display_name`, timezone (IANA, default UTC), `role` (`user` \| `admin`), `is_active` | The first registered user becomes `admin` |
| `organizations` | `name` (unique), `timezone` (IANA), `created_by_id` | A team that owns projects and connections. Deleted only when it owns nothing |
| `organization_members` | `organization_id`, `user_id`, `role` (`admin` \| `member`) | **Unique (`organization_id`, `user_id`)**. Deleted with the organization or the user |
| `git_connections` | `owner_id` or `organization_id`, `name`, `repo_url`, `auth_type` (`token` \| `basic` \| `none`), `username`, `secret_enc`, commit\_url\_template (nullable), `last_test_at`, `last_test_ok` | `secret_enc` = Fernet-encrypted token or password |
| `azure_connections` | `owner_id` or `organization_id`, `name`, `organization_url` (e.g. `https://dev.azure.com/acme`), `azure_project`, `pat_enc`, `last_test_at`, `last_test_ok` | PAT needs the *Work Items (Read & Write)* scope |
| `projects` | `owner_id` or `organization_id`, `name` (unique per owner), `git_connection_id`, `azure_connection_id`, `branches` (text\[\]; empty = default branch only), `ticket_pattern` (default `AB#(\d+)`), `comment_template`, `start_from` (date or SHA), `include_merge_commits` (bool, default false), `schedule_cron` (nullable), `schedule_enabled`, `schedule_last_fired_at`, `dry_run_default` | One repo → one board. `schedule_last_fired_at` makes each schedule slot fire once (section 7) |
| `project_shares` | `project_id`, `user_id`, `role` (`viewer` \| `editor`) | **Unique (`project_id`, `user_id`)**. Deleted with the project or the user |
| `sync_runs` | `project_id`, `trigger` (`manual` \| `scheduled`), `dry_run`, `status` (`queued` \| `running` \| `success` \| `partial` \| `failed` \| `skipped` \| `cancelled`), `started_at`, `finished_at`, `commits_scanned`, `comments_posted`, `skipped`, `errors`, `error_message`, `cancel_requested`, `triggered_by_id` (nullable) | One row per sync run. `triggered_by_id` is the user who started a manual run; null for scheduled runs |
| `sync_run_items` | `sync_run_id`, `position`, `commit_sha`, `commit_subject`, `branch`, `work_item_id`, `action` (`posted` \| `would_post` \| `skipped_duplicate` \| `skipped_not_found` \| `no_reference` \| `error`), `detail` | The audit trail shown in the UI. `position` orders the items (oldest commit first) |
| `posted_comments` | `project_id`, `commit_sha`, `work_item_id`, `azure_comment_id`, status (pending \| posted), `posted_at` | **Unique (`project_id`, `commit_sha`, `work_item_id`)**: this is what guarantees a commit is never posted twice |
| `project_cursors` | `project_id`, `branch`, `last_sha` | Where the last successful sync stopped on each branch |
| `refresh_tokens` | `user_id`, `token_hash`, `expires_at`, `revoked`, `revoked_at` | Lets sessions be revoked. `revoked_at` gives a rotated token a short grace period (section 10) |
| `audit_events` | `actor_id` (nullable), `actor_email`, `action` (e.g. `update`, `delete`, `sync`, `share`), `resource_type` (`project` \| `run` \| `git_connection` \| `azure_connection` \| `organization`), `resource_id`, `resource_name`, `owner_label` | What administrators did to anything not personally theirs. Names and owners are copied, so entries stay readable after the resource is gone |
| `ownership_transfers` | `admin_id`, `from_user_id`, `to_user_id`, `project_id` (null when everything was moved), `projects_moved`, `connections_moved`, `connections_copied`, `summary` | Audit trail of the administrator's transfers |

`posted_comments` is the source of truth for de-duplication. `project_cursors` is only an optimization so the app doesn't rescan the whole history. If the cursors are deleted, a full rescan still posts nothing twice. Deleting runs from the history never affects `posted_comments`.

**Access rules**

Personal connections are private to their owner; an organization's connections are seen, used and tested by its members and changed only by its admins. Every query on connections filters on their owner. All project and run queries go through one permission check, with the roles in this order: viewer < editor < owner. A user's role on a project is:

- **owner** for the owner of a personal project, for the admins of the organization that owns the project, and for every administrator of the instance;
- **editor** or **viewer** when the project is shared with them with that role;
- **viewer** for the members of the organization that owns the project, unless a share raises them to editor.

| Action | Viewer | Editor | Owner |
| --- | :---: | :---: | :---: |
| See the project, its runs and their items; test the pattern | ✓ | ✓ | ✓ |
| Start a dry run | ✓ | ✓ | ✓ |
| Cancel or delete a dry run they started themselves | ✓ | ✓ | ✓ |
| Start a real sync; cancel or delete any run; clear the history | | ✓ | ✓ |
| Change the settings: name, branches, pattern, template, start point, merge commits, schedule, dry-run default | | ✓ | ✓ |
| Change the Git or Azure connection | | | ✓ |
| Share the project, change or remove shares, delete the project | | | ✓ |

- A user with no access gets **404**, as if the project didn't exist. A user with access but too weak a role gets **403** with the code `insufficient_role`.
- Shared users never see or use the owner's connections directly. A project response carries secret-free summaries of its connections (name, repo URL, host, commit link pattern; organization URL and Azure project), so the UI can show them.
- Syncs of a shared project use the owner's connections, and its schedule runs in the owner's time zone (the organization's for an organization's project; such schedules keep running whatever happens to individual accounts).
- An organization's project uses only that organization's connections. A member who creates a project in an organization becomes its editor.
- Project names stay unique per owner, also when an editor renames a project.
- Anyone a personal project is shared with can leave it. Removing someone from an organization (or their leaving it) also deletes their shares on its projects.
- **Administrators of the instance may do everything.** They open any project with the owner role (a project response says `admin_access: true` when only that gives the access), read, test, change and delete any connection, and act as an admin of every organization. Secrets stay write-only for them too: they can replace a token, never read it. Their own project list (the dashboard) still holds only their own, their organizations' and their shared projects; everything else is reached from the admin pages.
- Whatever an administrator does to anything that isn't personally theirs (anything but reading: changes, syncs, run deletions, shares, moves, deletions, organization management), however they reach it (being an administrator, a share, or an organization they belong to), is recorded as an `audit_events` row in the same transaction as the action, and logged by the `app.audit` logger once committed. An action that fails leaves neither.
- Administrators also transfer personal projects (section 8) and can make a member the admin of an organization left without one.

**Organizations**

- Anyone can create an organization and becomes its first admin. Its time zone defaults to the creator's.
- Admins add members by exact email, change roles and remove members; anyone can leave. The last admin can neither leave nor step down.
- Members see each other (name and email), so a project can be shared with a member by name.
- A personal project moves into an organization (its owner, who must be a member); an organization's project moves out to a member (its admins). The connections come along, copied when the previous owner still uses them elsewhere; a non-admin who moves a project in stays its editor.
- An organization can be deleted only when it owns no projects and no connections.

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

1. First sync: `git clone --bare --no-tags --filter=blob:none` into `/data/repos/<project_id>` (branches only, see section 3). Later syncs: `git fetch --prune`.
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
- **404 on the existence check itself** (wrong organization or project): fail the run without moving any cursor. Treating it as "every work item is missing" would skip those commits for good.
- **429 or 503:** honor `Retry-After`. Otherwise use exponential backoff with jitter (1 s, 2 s, 4 s … up to 60 s, at most 5 attempts).
- Also honor Azure's `X-RateLimit-Delay` / `Retry-After` throttling headers.
- Make at most 5 concurrent requests per Azure organization, across all workers.

## 7. Sync engine

A sync run is one Celery task, `sync_project(project_id, trigger, dry_run, run_id)`. The API or the scheduler creates the `sync_runs` row first and passes its ID. A run is safe to repeat at any point: running it twice, or after a crash, never produces a duplicate comment.

**Triggers**

- **Manual:** the "Sync now" and "Dry run" buttons call `POST /api/v1/projects/{id}/sync`. The API creates a `sync_runs` row with status `queued` (recording who started it), sends the task to Celery, and returns the run ID straight away. Without `dry_run` in the body, the project's `dry_run_default` applies.
- **Scheduled:** each project has an optional 5-field cron expression (`schedule_cron`) and a switch (`schedule_enabled`). Celery Beat runs a dispatcher every minute, which reads the schedules from the database, so changes in the UI take effect within a minute and without a restart.
  - The dispatcher claims each due slot with an atomic update of `schedule_last_fired_at`, so a slot fires at most once, even with several schedulers. Saving a new or changed schedule sets it to "now": slots that already passed never fire.
  - The minimum interval is 5 minutes, set with `TT_MIN_SCHEDULE_MINUTES`.
  - Cron is evaluated in the **owner's** time zone: the user's (stored on their profile, default UTC), or the organization's for an organization's project.
  - Personal projects of turned-off accounts are not scheduled; an organization's projects always are.
  - Scheduled runs follow the project's `dry_run_default`.
- **Dry run:** a run with `dry_run=true` does every step except posting (it does check that the work items exist). Items are recorded as `would_post`, pending rows are not recovered, and no cursors are moved.

**One run, step by step**

1. Take a Redis lock `tt:sync:<project_id>` (value: the run ID) with a 30-minute time-to-live, refreshed by the run's heartbeat. If the lock is already held, mark the new run `skipped` and stop. Only one run (real or dry) per project at a time.
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
9. Finish the run with status `success`, `partial` (some errors or warnings, such as a missing branch or rewritten history) or `failed`, and store the counters. Release the lock.

**Cancelling**

`POST /runs/{id}/cancel` sets `cancel_requested`. A queued run never starts. A running run stops between commits, keeps what it already posted, and ends as `cancelled`; the next run continues from there.

**Stalled runs**

A running run updates its row every few seconds (the heartbeat). A queued or running run whose row hasn't changed for 10 minutes (or twice `TT_GIT_TIMEOUT`, if longer) is marked `failed` with an explanation, and its lock is cleared. The worker checks for these when it starts and before each run of the same project.

**Crash recovery**

If a run finds a `pending` row left behind by an earlier crash, it reads that work item's comments in Azure and looks for the `tt:{sha}` marker.

- Marker found: mark the row `posted` and don't post again.
- Marker not found: post the comment.

## 8. REST API contract

The API is JSON under `/api/v1`, with OpenAPI docs at `/api/docs`. Every endpoint except auth and health needs `Authorization: Bearer <access token>`. Resources the caller can't access return **404**, not 403, so their IDs don't leak; a shared project with too weak a role returns **403** `insufficient_role` (section 4, *Access rules*). Secrets are write-only: responses return `"has_secret": true` and never the value.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/auth/config` | Public: whether registration is open |
| POST | `/auth/register` | Create an account. Can be turned off with `TT_ALLOW_REGISTRATION=false` |
| POST | `/auth/login` | Returns an access token (15 min) and a refresh token (7 days, httpOnly cookie) |
| POST | `/auth/refresh` · `/auth/logout` | Rotate or revoke the refresh token. Require the header `X-Requested-With: TicketTrail` (CSRF) |
| GET / PATCH | `/me` | Profile: name, time zone, password change |
| GET / POST | `/git-connections` | List / create: the caller's own, an organization's with `?organization_id=` (members list) / `organization_id` in the body (admins create), or another user's with `?owner_id=` (administrators) |
| GET / PATCH / DELETE | `/git-connections/{id}` | Read / update / delete. Delete is refused (409, naming the projects) while a project uses the connection |
| POST | `/git-connections/{id}/test` | Runs `git ls-remote` in the worker, returns `{ok, branches[], default_branch, error}` |
| GET / POST | `/azure-connections` | List / create, personal or an organization's, as for Git connections |
| GET / PATCH / DELETE | `/azure-connections/{id}` | Read / update / delete. Delete is refused while a project uses the connection |
| POST | `/azure-connections/{id}/test` | Runs in the worker, returns `{ok, project_name, error}` |
| GET / POST | `/projects` | List (`?scope=all\|owned\|organizations\|shared`, default `all`) / create (personal, or in an organization with `organization_id`, any member). Each project carries the caller's `role`, its `owner` (a user, null for an organization's) and `organization`, the number of `shares`, `schedule_timezone` (the owner's or the organization's), the connection summaries and the dashboard fields (`last_run`, `next_run_at`, `comments_posted`) |
| GET / PATCH / DELETE | `/projects/{id}` | Read (viewer) / update (editor; connections owner only) / delete (owner) |
| POST | `/projects/test-pattern` | Body `{pattern, samples[]}`: try a pattern before the project exists |
| POST | `/projects/{id}/test-pattern` | Body `{pattern?, samples[]}` (default: the saved pattern), returns the IDs found in each sample |
| POST | `/projects/{id}/sync` | Body `{dry_run?: bool}` (default: the project's `dry_run_default`). Returns `202` with `{run_id}`. Dry run: viewer; real sync: editor |
| GET | `/projects/{id}/runs` | Paginated run history, newest first |
| DELETE | `/projects/{id}/runs` | Editor: delete the finished runs, optionally only `?dry_run=true\|false`. Returns `{deleted}` |
| POST | `/projects/{id}/move` | Owner role: body `{organization_id}` (a personal project into an organization the caller belongs to) or `{to_user_id}` (an organization's project to one of its active members). Returns `{project_id, summary}` |
| GET / POST | `/organizations` | The caller's organizations (with their role and counts) / create one (anyone; the creator becomes admin) |
| GET / PATCH / DELETE | `/organizations/{id}` | Read (members) / rename or change the time zone (admins) / delete (admins, only when it owns nothing: 409 `organization_not_empty`) |
| GET / POST | `/organizations/{id}/members` | List (members) / add `{email, role}` (admins) |
| PATCH / DELETE | `/organizations/{id}/members/{user_id}` | Change the role (admins) / remove (admins) or leave (oneself). 409 `last_admin` for the last admin |
| GET / POST | `/projects/{id}/shares` | Owner: list shares / share with `{email, role}` (the exact email of an active user; otherwise 404 `user_not_found`) |
| PATCH / DELETE | `/projects/{id}/shares/{user_id}` | Owner: change the role / remove the share. A user can also delete their own share (leave) |
| GET | `/runs/{run_id}` | Run detail with counters and `counts_by_action` |
| GET | `/runs/{run_id}/items` | Paginated items, oldest commit first, filterable by `action` |
| POST | `/runs/{run_id}/cancel` | Cooperative cancel: the worker checks a flag between commits. 409 if already finished |
| DELETE | `/runs/{run_id}` | Delete a finished run and its items (409 while active) |
| GET | `/admin/users` · PATCH `/admin/users/{id}` | Admin only: list users (with their project count), turn accounts on or off |
| GET | `/admin/projects` | Admin only: every project with its owner, share count and last run (`?owner_id=` to filter). No settings |
| POST | `/admin/projects/{id}/transfer` | Admin only: body `{to_user_id}`. Gives the project and its connections to an active user; a connection the previous owner still uses elsewhere is copied |
| POST | `/admin/users/{id}/transfer` | Admin only: body `{to_user_id}`. Gives everything the user owns personally (projects and connections) to an active user; organizations' rows stay |
| GET | `/admin/organizations` | Admin only: every organization with its members, admins and counts |
| GET | `/admin/activity` | Admin only: the `audit_events`, newest first (`?actor_id=` to filter) |
| GET | `/admin/git-connections` · `/admin/azure-connections` | Admin only: every connection with its owner (user or organization) and the number of projects using it. Secrets stay write-only |
| POST | `/admin/organizations/{id}/admins` | Admin only: body `{user_id}`, a member who becomes an admin of the organization |
| GET | `/admin/transfers` | Admin only: the transfer history, newest first |
| GET | `/health` · `/ready` | Liveness / readiness (database, Redis) |

Run actions follow the access rules: cancel and delete need an editor, except a viewer's own dry runs. The administrator's project transfer refuses an organization's project (409 `organization_project`): its admins move it. Transfers keep secrets encrypted as they are, carry the run history and posted comments along, drop a share the new owner had on the project, and add a suffix such as "(from Marco)" to names the new owner already uses.

Errors use one shape: `{"error": {"code": "string", "message": "human readable", "details": {}}}`. List endpoints take `?page=&page_size=` (default 25, max 100).

## 9. Frontend pages

The UI is a responsive single-page app with light and dark themes. Everything a user configures lives under **Settings**. The main page is the **Dashboard**.

| Page | Route | Contents |
| --- | --- | --- |
| Login / Register | `/login`, `/register` | Email + password. Register is hidden when registration is turned off |
| Dashboard | `/` | One card per project: last run status and time, next scheduled run, comments posted, and **Sync now** / **Dry run** buttons. Projects shared with the user appear under **Shared with me**, with their role and owner |
| Project detail | `/projects/:id` | Run history table (who started each manual run), **Delete** per run and **Clear dry runs**. **Share** (owner) opens a drawer to share by email, change roles and remove shares; **Leave** (shared users). Click a run to open its item list (commit SHA, message subject, work item ID with a link to Azure, action, detail), with filters by action, **Cancel** and **Delete** |
| Settings → Git connections | `/settings/git` | List plus a form: name, repo URL, auth type, username (prefilled for the detected host), token or password, commit URL template, **Test connection** (shows the branches found) |
| Settings → Azure connections | `/settings/azure` | List plus a form: name, organization URL, project, PAT, **Test connection** |
| Settings → Projects | `/settings/projects`, `/settings/projects/new`, `/settings/projects/:id` | List of the projects the user can see, then the wizard: pick a Git connection → branches → pick an Azure connection → ticket pattern with **live pattern tester** → comment template with **live preview** → start point → schedule. For an editor the connections are locked; a viewer is told only editors can change the settings |
| Settings → Organizations | `/settings/organizations`, `/settings/organizations/:id` | The user's organizations and **New organization**. An organization's page: name and time zone (admins), members (add by email, roles, remove, leave), its Git and Azure connections (admins add, edit, delete), its projects and **New project** |
| Settings → Profile | `/settings/profile` | Display name, time zone, change password |
| Admin → Users | `/admin/users` | Admins only: list users, turn accounts on or off, **Transfer all** of a user's projects and connections |
| Admin → Projects | `/admin/projects` | Admins only: every project with its owner (a user or an organization), a link to open it with full rights, **Transfer** of personal projects to another user, and the transfer history |
| Admin → Activity | `/admin/activity` | Admins only: what administrators did to other users' data (when, who, action, resource with a link while it exists, owner) |
| Admin → Connections | `/admin/connections` | Admins only: every Git and Azure connection with its owner, to edit (and test), or delete |
| Admin → Organizations | `/admin/organizations` | Admins only: every organization with its admins, a link to manage it as its admin; **Make admin** for a member |

**UI rules**

- Secret fields show `••••••• (saved)` once saved. Typing a new value replaces the secret; leaving the field empty keeps it.
- The schedule field offers presets (every 15 min, hourly, daily at 08:00, weekdays at 08:00) plus a custom cron. It shows the next three run times in plain language.
- The run detail page polls every 2 s while the run is `queued` or `running`.
- Every destructive action asks for confirmation.
- Buttons follow the access rules (section 4): what a user's role doesn't allow isn't shown. The API enforces the same rules.
- All forms validate on the client with Zod, using the same rules as the API (pattern rules, URL format, cron syntax).

## 10. Security

TicketTrail stores other systems' credentials, so the security rules below are requirements, not nice-to-haves.

- **Secrets at rest:** Fernet-encrypt every token, PAT and password with `TT_ENCRYPTION_KEY`. Support key rotation with `TT_ENCRYPTION_KEY_OLD` and a `manage.py rotate-keys` command.
- **Secrets in transit and in logs:** never return secrets from the API or log them. A logging filter scrubs `Authorization` headers, URLs with credentials in them, and known secret fields. Git error output is cleaned before it is stored in `sync_run_items.detail`.
- **Tenant isolation:** connection queries go through an owner filter; project and run queries go through the one permission check of section 4 (owner, organization membership, shared with the caller, or administrator). Add tests where user B tries to read, change, sync and test user A's resources, and where viewers and editors try what their role doesn't allow.
- **Passwords:** Argon2id hashing, at least 10 characters, and login rate limits (5 attempts a minute per IP and per email, counted in Redis; if Redis is down, logins are not blocked).
- **Tokens:** JWT access tokens signed with HS256 using `TT_JWT_SECRET`. Refresh tokens are httpOnly and SameSite=Strict cookies (Secure when `TT_PUBLIC_URL` is https), stored hashed, and rotated each time they are used. Reusing a rotated token signs the user out everywhere, except within a 30-second grace period (two tabs refreshing at once).
- **Accounts turned off** by an admin are signed out everywhere at once, and their scheduled syncs stop.
- **SSRF guard:** repo and Azure URLs must be `https://`. Block private, loopback and link-local addresses unless `TT_ALLOW_PRIVATE_HOSTS=true` (needed for self-hosted Git on the LAN).
- **Containers:** run as a non-root user, mount the filesystem read-only except `/data`, and add healthchecks.
- **Web:** strict CORS (same origin via the Nginx proxy), security headers (CSP, HSTS when served over TLS), and CSRF protection on the refresh and logout endpoints (a required `X-Requested-With: TicketTrail` header).
- **Least privilege guidance:** the UI tells users which minimum scopes their PATs need: *Code (Read)* for Git and *Work Items (Read & Write)* for Azure.

## 11. Repository layout and configuration

Everything lives in one monorepo, with the backend and frontend as separate Docker build contexts.

```text
tickettrail/
├── docker-compose.yml          # production-like stack
├── docker-compose.dev.yml      # hot reload, exposed ports
├── docker-compose.e2e.yml      # adds a fake Git / Azure DevOps server for the Playwright test
├── .env.example
├── README.md
├── .github/workflows/ci.yml    # lint, types, tests, image build, e2e, secret-leak check
├── scripts/secret-leak-check.sh
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── manage.py               # rotate-keys
│   ├── alembic/
│   └── app/
│       ├── main.py             # FastAPI app factory
│       ├── config.py           # pydantic-settings, TT_* env vars
│       ├── db/                 # models, session, repositories (owner-scoped, access rules, transfers)
│       ├── api/access.py       # permission checks: projects, runs, organizations, connections
│       ├── api/v1/             # routers: auth, me, git, azure, projects, sharing, organizations, runs, admin
│       ├── core/               # security, crypto, logging, errors, cron, rate limits
│       ├── integrations/
│       │   ├── git/            # GitClient, host detection, URL builders
│       │   └── trackers/       # WorkItemTracker interface, AzureBoardsClient
│       ├── sync/               # parser, template renderer, engine, locks
│       └── worker/             # celery app, tasks, schedule dispatcher
│   └── tests/                  # unit/, integration/, fixtures/ (sample repos, fake Azure)
└── frontend/
    ├── Dockerfile              # build stage + nginx stage
    ├── nginx.conf
    ├── e2e/                    # Playwright test and its fixtures server
    └── src/                    # pages/, components/, api/, hooks/, lib/, schemas/
```

**Environment variables** (all prefixed `TT_`, documented in `.env.example`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `TT_DATABASE_URL` | `postgresql+psycopg://tt:tt@db:5432/tickettrail` | Database connection. Compose builds it from `TT_DB_PASSWORD` |
| `TT_DB_PASSWORD` | `tt` | Compose only: the Postgres password. Change it on first start |
| `TT_REDIS_URL` | `redis://redis:6379/0` | Broker and locks |
| `TT_ENCRYPTION_KEY` | *(required)* | Fernet key for secrets |
| `TT_ENCRYPTION_KEY_OLD` | *(empty)* | The previous key during a key rotation |
| `TT_JWT_SECRET` | *(required)* | Signs JWTs |
| `TT_ALLOW_REGISTRATION` | `true` | Public sign-up on or off |
| `TT_ALLOW_PRIVATE_HOSTS` | `false` | SSRF guard exception |
| `TT_GIT_TIMEOUT` | `300` | Seconds per Git command |
| `TT_MIN_SCHEDULE_MINUTES` | `5` | Shortest schedule interval allowed |
| `TT_AZURE_MAX_CONCURRENCY` | `5` | Concurrent requests per Azure organization |
| `TT_LOG_LEVEL` | `INFO` | Logging level; logs are JSON |
| `TT_PUBLIC_URL` | `http://localhost:8080` | Used in links and cookies |
| `TT_HTTP_PORT` | `8080` | Compose only: the host port the frontend publishes |

Volumes: `pg_data` (database) and `repos_data` (Git clones). Only `frontend` publishes a port (8080 by default). TLS is expected from a reverse proxy in front of the stack.

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
  - `GitClient` (bare clone and fetch, commit listing, cursors, force-push fallback).
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
  - The schedule dispatcher (Celery Beat, schedules read from the database), schedule switch, time-zone handling and minimum interval.
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

**M8 – Sharing** (added after M7, built in two phases with a gate after each)

- **S1 – Sharing with users and administrator transfers** *(done)*
  - *Build:*
    - `project_shares`, the access rules of section 4 in one permission check, and `triggered_by_id` on runs.
    - Share endpoints (by exact email; change role; remove; leave) and the `scope` filter on `/projects`.
    - Admin: list every project, transfer one project or everything a user owns, and the transfer history (`ownership_transfers`).
    - UI: Share drawer, **Shared with me**, role badges, buttons that follow the role, locked connections for editors, Admin → Projects, **Transfer all**.
  - *Accept when:*
    - A viewer sees the project and starts dry runs, and gets 403 on everything else; an editor syncs and edits but can't change connections, share or delete.
    - A user the project isn't shared with gets 404 on every project and run endpoint.
    - A transfer keeps secrets encrypted, copies connections the previous owner still uses, and is recorded.
    - The Playwright test covers sharing with a viewer.
- **S2 – Organizations** *(done)*
  - *Build:*
    - `organizations` and `organization_members`; projects and connections owned by a user or an organization; roles derived from membership (admins: owner; members: viewer, raised by shares).
    - Organization and member endpoints, organization connections, projects created in or moved into and out of an organization, schedules in the organization's time zone.
    - Admin: organizations' projects in the project list (not transferable), the organization list and **Make admin**.
    - UI: Settings → Organizations and an organization's page, the Owner choice in the wizard, **Move to an organization** / **Move to a member**, member picker in the Share drawer, one dashboard section per organization, Admin → Organizations.
  - *Accept when:*
    - A member sees the organization's projects as viewer and becomes editor through a share; admins own every project; outsiders get 404.
    - Members use and test the organization's connections without seeing tokens; only admins change them.
    - Removing a member ends their access; the last admin can't leave; a non-empty organization can't be deleted.
    - The Playwright test moves a project into an organization and the member finds it there.
- **S3 – Administrators see everything** *(done)*
  - *Build:* the owner role on every project and admin rights on every organization for administrators, any connection readable and changeable (secrets still write-only), `?owner_id=` on the connection lists, `/admin/git-connections` and `/admin/azure-connections`, the `app.audit` log, `admin_access` on projects; UI: projects and organizations open from the admin pages, Admin → Connections, the administrator banner on a project.
  - *Accept when:* an administrator syncs, edits, shares and deletes another user's project and edits or deletes their connections; their dashboard lists only their own projects; tokens never appear in any response; each such action is in the audit log; regular users still get 404.
- **Activity page** *(done)*: `audit_events`, `GET /admin/activity` and Admin → Activity, replacing the logs as the place to read what administrators did.
- Out of scope: instance-wide visibility for regular users, and public links.

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
- **Access suite:** for each role, check what it may and may not do (section 4), plus the share endpoints, the administrator's full access (and its audit log) and transfers.
- **End to end (Playwright):** register → create both connections → create a project → dry run → real sync (Azure mocked) → see the history → share the project with a viewer → create an organization with the viewer as a member and move the project into it; the viewer finds it in the organization's section, starts a dry run and can't sync.

**Quality bar**

- Backend: `ruff` + `mypy --strict` on `app/`, coverage ≥ 80% on `sync/` and `integrations/`.
- Frontend: `eslint` + `tsc --noEmit`, with no `any` in the API layer.
- Every endpoint has typed Pydantic schemas and appears correctly in OpenAPI.
- No `TODO` left without an issue reference in the final milestone.

## 14. Changes agreed during the build

Decisions taken at the milestone gates, already reflected in the sections above.

| Milestone | Change | Why |
| --- | --- | --- |
| M2 | Refresh cookies get the Secure flag only when `TT_PUBLIC_URL` is https | Plain-HTTP local installs could not log in otherwise |
| M2 | Reusing a rotated refresh token signs the user out everywhere, with a 30-second grace period | Detects stolen tokens without breaking two tabs refreshing at once |
| M3 | Connection tests run in the worker; `POST /projects/test-pattern` added | The API never talks to Git or Azure; patterns can be tried before saving |
| M4 | Bare, blobless clone of branches instead of `git clone --mirror` | A mirror also fetches `refs/pull/*`, gigabytes on busy GitHub repos |
| M4 | `sync_run_items` gained `position`, `commit_subject` and `branch` | Stable ordering and a readable item list |
| M5 | A 404 on the Azure existence check fails the run | Otherwise a wrong organization or project would skip every commit for good |
| M5 | Stalled runs are closed after 10 minutes without a heartbeat (anticipated from M6) | A crashed worker can't block a project |
| M6 | A minute dispatcher on plain Celery Beat instead of a database-backed beat library | Fewer moving parts; schedules still change at runtime |
| M6 | New run status `cancelled` | A cancelled run is neither a success nor a failure |
| M6 | Runs can be deleted (one, or all dry runs) | Keeps the history readable; never re-posts a comment |
| M7 | `TT_DB_PASSWORD` (default `tt`) and a "First start" section in the README | Defaults that work out of the box, changed on first start |
| M8/S1 | Project sharing (viewer / editor), administrator transfers | Projects survive a colleague leaving; teams can work on the same project |
| M8/S2 | Organizations: members are viewers by default, raised to editor per project with a share | Least privilege by default; editing rights are given project by project |
| M8/S3 | Administrators see and may do everything (replacing "administrators don't see users' data"); tokens stay write-only; their actions on others' data are logged | Nothing is out of an administrator's reach; secrets still never leave the server |
| M8 | Admin → Activity: administrators' actions stored in `audit_events`, not only in the logs | The record survives log rotation and can be read in the UI |
