import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as api from '../api/runs';
import type { ItemAction } from '../api/types';

export const runKeys = {
  list: (projectId: string) => ['runs', projectId] as const,
  detail: (runId: string) => ['run', runId] as const,
  items: (runId: string) => ['run-items', runId] as const,
};

export function useRuns(projectId: string, page: number) {
  return useQuery({
    queryKey: [...runKeys.list(projectId), page],
    queryFn: () => api.listRuns(projectId, page),
    placeholderData: keepPreviousData,
  });
}

export function useRun(runId: string) {
  return useQuery({ queryKey: runKeys.detail(runId), queryFn: () => api.getRun(runId) });
}

export function useRunItems(runId: string, page: number, action: ItemAction | null) {
  return useQuery({
    queryKey: [...runKeys.items(runId), page, action],
    queryFn: () => api.listRunItems(runId, page, action),
    placeholderData: keepPreviousData,
  });
}

export function useStartSync(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dryRun: boolean) => api.startSync(projectId, dryRun),
    onSettled: () => queryClient.invalidateQueries({ queryKey: runKeys.list(projectId) }),
  });
}
