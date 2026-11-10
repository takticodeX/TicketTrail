import { apiRequest } from './client';
import type { ItemAction, Page, SyncRun, SyncRunDetail, SyncRunItem, WorkItemSearchResult } from './types';

export const startSync = (projectId: string, dryRun: boolean) =>
  apiRequest<{ run_id: string }>(`/projects/${projectId}/sync`, {
    method: 'POST',
    body: { dry_run: dryRun },
  });

export const listRuns = (projectId: string, page: number, pageSize = 20) =>
  apiRequest<Page<SyncRun>>(`/projects/${projectId}/runs?page=${page}&page_size=${pageSize}`);

export const getRun = (runId: string) => apiRequest<SyncRunDetail>(`/runs/${runId}`);

export const cancelRun = (runId: string) =>
  apiRequest<SyncRun>(`/runs/${runId}/cancel`, { method: 'POST' });

export const deleteRun = (runId: string) => apiRequest<void>(`/runs/${runId}`, { method: 'DELETE' });

/** Delete a project's finished runs; dryRun true deletes only dry runs. */
export const deleteRuns = (projectId: string, dryRun?: boolean) =>
  apiRequest<{ deleted: number }>(
    `/projects/${projectId}/runs${dryRun === undefined ? '' : `?dry_run=${dryRun}`}`,
    { method: 'DELETE' },
  );

export const listRunItems = (runId: string, page: number, action: ItemAction | null, pageSize = 50) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (action) params.set('action', action);
  return apiRequest<Page<SyncRunItem>>(`/runs/${runId}/items?${params.toString()}`);
};

// --- Reviewing a dry run ----------------------------------------------------------------------

/** Work items of the project's board: open first, closed last. */
export const searchWorkItems = (projectId: string, query: string, signal?: AbortSignal) =>
  apiRequest<WorkItemSearchResult>(
    `/projects/${projectId}/work-items?${new URLSearchParams({ q: query }).toString()}`,
    { signal },
  );

/** Post a dry-run row to this work item; the commit stays linked to it from now on. */
export const setItemWorkItem = (runId: string, itemId: string, workItemId: string) =>
  apiRequest<SyncRunItem>(`/runs/${runId}/items/${itemId}/work-item`, {
    method: 'PUT',
    body: { work_item_id: workItemId },
  });

/** Deselect a row for good (selected: false), or select it again. */
export const setItemSelected = (runId: string, itemId: string, selected: boolean) =>
  apiRequest<SyncRunItem>(`/runs/${runId}/items/${itemId}/exclude`, {
    method: selected ? 'DELETE' : 'POST',
  });

/** Post the reviewed dry run's selected rows: a new run, without a rescan. */
export const postSelected = (runId: string) =>
  apiRequest<{ run_id: string }>(`/runs/${runId}/post`, { method: 'POST' });
