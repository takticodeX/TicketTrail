// Mirrors the backend's Pydantic schemas (backend/app/api/v1/schemas.py).

export type UserRole = 'user' | 'admin';

export interface User {
  id: string;
  email: string;
  display_name: string;
  timezone: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}

export interface AuthConfig {
  allow_registration: boolean;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  display_name?: string;
}

export interface UserUpdate {
  display_name?: string;
  timezone?: string;
  current_password?: string;
  new_password?: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type GitAuthType = 'token' | 'basic' | 'none';
export type GitHost = 'azure_repos' | 'github' | 'gitlab' | 'bitbucket' | 'generic';

export interface GitConnection {
  id: string;
  name: string;
  /** Set when an organization owns the connection. */
  organization_id: string | null;
  repo_url: string;
  auth_type: GitAuthType;
  username: string | null;
  has_secret: boolean;
  commit_url_template: string | null;
  /** The commit link actually used, with a {sha} placeholder; "" for unknown hosts. */
  commit_url_pattern: string;
  host: GitHost;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface GitConnectionInput {
  name: string;
  repo_url: string;
  auth_type: GitAuthType;
  username: string | null;
  /** Write-only. Omit or send "" to keep the saved secret. */
  secret?: string;
  commit_url_template: string | null;
  /** On create only: the organization that owns it (its admins only). */
  organization_id?: string;
}

export interface GitTestResult {
  ok: boolean;
  branches: string[];
  default_branch: string | null;
  error: string | null;
}

/** The kind of board a connection talks to. */
export type BoardKind = 'azure';

export interface BoardConnection {
  id: string;
  name: string;
  /** Set when an organization owns the connection. */
  organization_id: string | null;
  kind: BoardKind;
  /** Azure: the organization URL. */
  url: string;
  /** Azure: the project name. */
  scope: string;
  has_secret: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface BoardConnectionInput {
  name: string;
  /** On create only; the kind of a saved connection is fixed. */
  kind?: BoardKind;
  url: string;
  scope: string;
  /** Write-only (PAT). Omit or send "" to keep the saved one. */
  secret?: string;
  /** On create only: the organization that owns it (its admins only). */
  organization_id?: string;
}

export interface BoardTestResult {
  ok: boolean;
  /** The Azure project's name. */
  scope_name: string | null;
  error: string | null;
}

export interface Project {
  id: string;
  name: string;
  git_connection_id: string;
  board_connection_id: string;
  branches: string[];
  ticket_pattern: string;
  comment_template: string;
  start_from: string | null;
  include_merge_commits: boolean;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  dry_run_default: boolean;
  created_at: string;
  updated_at: string;
  // The dashboard summary, computed by the API.
  last_run?: SyncRun | null;
  /** Next scheduled run (UTC), when the schedule is on. */
  next_run_at?: string | null;
  comments_posted?: number;
  // Sharing, computed by the API.
  /** Your role on this project. */
  role: ProjectRole;
  /** Null when an organization owns the project. */
  owner: UserSummary | null;
  organization: OrganizationSummary | null;
  /** The owner's time zone: the schedule runs in it. */
  schedule_timezone: string;
  /** Number of users the project is shared with. */
  shares: number;
  /** You see it only because you are an administrator. */
  admin_access: boolean;
  /** The connections without their secrets, so shared users can show them too. */
  git_connection: ProjectGitSummary | null;
  board_connection: ProjectBoardSummary | null;
}

export type ProjectRole = 'owner' | 'editor' | 'viewer';
export type ShareRole = Exclude<ProjectRole, 'owner'>;

export interface UserSummary {
  id: string;
  display_name: string;
  email: string;
}

export type ProjectGitSummary = Pick<GitConnection, 'id' | 'name' | 'repo_url' | 'host' | 'commit_url_pattern'>;
export type ProjectBoardSummary = Pick<BoardConnection, 'id' | 'name' | 'kind' | 'url' | 'scope'>;

export type ProjectInput = Omit<
  Project,
  | 'id'
  | 'created_at'
  | 'updated_at'
  | 'last_run'
  | 'next_run_at'
  | 'comments_posted'
  | 'role'
  | 'owner'
  | 'organization'
  | 'schedule_timezone'
  | 'shares'
  | 'admin_access'
  | 'git_connection'
  | 'board_connection'
> & {
  /** On create only: the organization that owns it (any member). */
  organization_id?: string;
};

export interface OrganizationSummary {
  id: string;
  name: string;
}

export type OrganizationRole = 'admin' | 'member';

export interface Organization extends OrganizationSummary {
  timezone: string;
  /** Your role in the organization. */
  role: OrganizationRole;
  members: number;
  projects: number;
  created_at: string;
}

export interface OrganizationMember {
  user: UserSummary;
  role: OrganizationRole;
  created_at: string;
}

export interface ProjectShare {
  user: UserSummary;
  role: ShareRole;
  created_at: string;
}

export interface PatternTestResponse {
  pattern: string;
  results: { ids: string[]; error: string | null }[];
}

export type RunStatus =
  | 'queued'
  | 'running'
  | 'success'
  | 'partial'
  | 'failed'
  | 'skipped'
  | 'cancelled';
export type RunTrigger = 'manual' | 'scheduled';
export type ItemAction =
  | 'posted'
  | 'would_post'
  | 'skipped_duplicate'
  | 'skipped_not_found'
  | 'no_reference'
  | 'error'
  | 'excluded';

export interface SyncRun {
  id: string;
  project_id: string;
  trigger: RunTrigger;
  dry_run: boolean;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  commits_scanned: number;
  comments_posted: number;
  skipped: number;
  errors: number;
  /** Why the run failed, or warnings for a partial run. */
  error_message: string | null;
  /** The user asked to cancel; a running run stops at the next commit. */
  cancel_requested: boolean;
  /** Who started a manual run; null for scheduled runs. */
  triggered_by?: UserSummary | null;
  /** For a Post selected run: the reviewed dry run it posts. */
  source_run_id?: string | null;
}

export interface SyncRunDetail extends SyncRun {
  counts_by_action: Partial<Record<ItemAction, number>>;
}

export interface SyncRunItem {
  id: string;
  commit_sha: string;
  commit_subject: string;
  branch: string;
  /** A string: some boards' IDs don't fit a JavaScript number. */
  work_item_id: string | null;
  action: ItemAction;
  detail: string | null;
  /** The work item was linked by hand in a review. */
  manual?: boolean;
}

/** A work item of the board, offered by the review's picker. */
export interface WorkItemOption {
  id: string;
  title: string;
  /** Bug, Task, User Story, ... */
  type: string;
  state: string;
  /** Closed, done or removed: listed last. */
  closed: boolean;
}

export interface WorkItemSearchResult {
  ok: boolean;
  items: WorkItemOption[];
  error: string | null;
}

export interface ErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}
