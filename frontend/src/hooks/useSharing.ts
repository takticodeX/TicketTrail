import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as api from '../api/sharing';
import type { ShareRole } from '../api/types';
import { settingsKeys } from './useSettings';

export const shareKeys = {
  list: (projectId: string) => ['shares', projectId] as const,
};

export function useShares(projectId: string, enabled = true) {
  return useQuery({
    queryKey: shareKeys.list(projectId),
    queryFn: () => api.listShares(projectId),
    enabled,
  });
}

function useShareMutation<T, R>(projectId: string, mutationFn: (args: T) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: shareKeys.list(projectId) });
      // The project's share count changes.
      void queryClient.invalidateQueries({ queryKey: settingsKeys.projects });
    },
  });
}

export const useAddShare = (projectId: string) =>
  useShareMutation(projectId, ({ email, role }: { email: string; role: ShareRole }) =>
    api.addShare(projectId, email, role),
  );

export const useUpdateShare = (projectId: string) =>
  useShareMutation(projectId, ({ userId, role }: { userId: string; role: ShareRole }) =>
    api.updateShare(projectId, userId, role),
  );

export const useRemoveShare = (projectId: string) =>
  useShareMutation(projectId, (userId: string) => api.removeShare(projectId, userId));
