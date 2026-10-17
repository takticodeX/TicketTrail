import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as api from '../api/runs';
import type { ItemAction } from '../api/types';
import { POLL_MS, isRunActive } from '../lib/runs';

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
    // Keep polling while any run on the page is queued or running.
    refetchInterval: (query) => (query.state.data?.items.some(isRunActive) ? POLL_MS : false),
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: runKeys.detail(runId),
    queryFn: () => api.getRun(runId),
    refetchInterval: (query) =>
      query.state.data && isRunActive(query.state.data) ? POLL_MS : false,
  });
}

export function useRunItems(runId: string, page: number, action: ItemAction | null, live: boolean) {
  return useQuery({
    queryKey: [...runKeys.items(runId), page, action],
    queryFn: () => api.listRunItems(runId, page, action),
    placeholderData: keepPreviousData,
    refetchInterval: live ? POLL_MS : false,
  });
}

export function useStartSync(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dryRun: boolean) => api.startSync(projectId, dryRun),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: runKeys.list(projectId) });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });
}

export function useCancelRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  });
}
