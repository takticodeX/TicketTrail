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
}

export interface GitTestResult {
  ok: boolean;
  branches: string[];
  default_branch: string | null;
  error: string | null;
}

export interface AzureConnection {
  id: string;
  name: string;
  organization_url: string;
  azure_project: string;
  has_secret: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface AzureConnectionInput {
  name: string;
  organization_url: string;
  azure_project: string;
  /** Write-only. Omit or send "" to keep the saved PAT. */
  pat?: string;
}

export interface AzureTestResult {
  ok: boolean;
  project_name: string | null;
  error: string | null;
}

export interface Project {
  id: string;
  name: string;
  git_connection_id: string;
  azure_connection_id: string;
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
}

export type ProjectInput = Omit<
  Project,
  'id' | 'created_at' | 'updated_at' | 'last_run' | 'next_run_at' | 'comments_posted'
>;

export interface PatternTestResponse {
  pattern: string;
  results: { ids: number[]; error: string | null }[];
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
  | 'error';

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
}

export interface SyncRunDetail extends SyncRun {
  counts_by_action: Partial<Record<ItemAction, number>>;
}

export interface SyncRunItem {
  id: string;
  commit_sha: string;
  commit_subject: string;
  branch: string;
  work_item_id: number | null;
  action: ItemAction;
  detail: string | null;
}

export interface ErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}
