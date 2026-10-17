import { apiRequest } from './client';
import type { ItemAction, Page, SyncRun, SyncRunDetail, SyncRunItem } from './types';

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

export const listRunItems = (runId: string, page: number, action: ItemAction | null, pageSize = 50) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (action) params.set('action', action);
  return apiRequest<Page<SyncRunItem>>(`/runs/${runId}/items?${params.toString()}`);
};
