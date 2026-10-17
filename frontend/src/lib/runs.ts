import type { AzureConnection, ItemAction, RunStatus, SyncRun } from '../api/types';

export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  success: 'Success',
  partial: 'Partial',
  failed: 'Failed',
  skipped: 'Skipped',
};

export const STATUS_COLORS: Record<RunStatus, string> = {
  queued: 'gray',
  running: 'blue',
  success: 'teal',
  partial: 'yellow',
  failed: 'red',
  skipped: 'gray',
};

export const ACTION_LABELS: Record<ItemAction, string> = {
  posted: 'Posted',
  would_post: 'Would post',
  skipped_duplicate: 'Already posted',
  skipped_not_found: 'Work item not found',
  no_reference: 'No reference',
  error: 'Error',
};

export const ACTION_COLORS: Record<ItemAction, string> = {
  posted: 'teal',
  would_post: 'blue',
  skipped_duplicate: 'gray',
  skipped_not_found: 'orange',
  no_reference: 'gray',
  error: 'red',
};

/** The order of the filter buttons on the run page. */
export const ACTION_ORDER: ItemAction[] = [
  'would_post',
  'posted',
  'no_reference',
  'skipped_duplicate',
  'skipped_not_found',
  'error',
];

export function isRunActive(run: Pick<SyncRun, 'status'>): boolean {
  return run.status === 'queued' || run.status === 'running';
}

/** "1 min 05 s", "12 s", or null while the run hasn't finished. */
export function runDuration(run: Pick<SyncRun, 'started_at' | 'finished_at'>): string | null {
  if (!run.started_at || !run.finished_at) return null;
  const seconds = Math.max(
    0,
    Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000),
  );
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, '0')} s`;
}

export function workItemUrl(connection: Pick<AzureConnection, 'organization_url' | 'azure_project'>, id: number): string {
  return `${connection.organization_url}/${encodeURIComponent(connection.azure_project)}/_workitems/edit/${id}`;
}

/** The commit link from the Git connection's pattern, or null for unknown hosts. */
export function commitUrl(pattern: string | undefined, sha: string): string | null {
  return pattern ? pattern.replaceAll('{sha}', sha) : null;
}

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export function formatDateTime(value: string | null): string {
  return value ? dateTime.format(new Date(value)) : '—';
}
