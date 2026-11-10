import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as api from '../api/settings';
import type { BoardConnectionInput, GitConnectionInput, ProjectInput } from '../api/types';
import { POLL_MS, isRunActive } from '../lib/runs';

export const settingsKeys = {
  git: ['git-connections'] as const,
  boards: ['board-connections'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
};

/** A query-key suffix for whose connections are listed; empty for your own. */
function scopeKey({ organizationId, ownerId }: api.ConnectionScope): string[] {
  return organizationId ? [organizationId] : ownerId ? [`user:${ownerId}`] : [];
}

/**
 * Yours, an organization's (`organizationId`) or, for administrators, another user's
 * (`ownerId`). Keys share a prefix, so saving one refreshes all.
 */
export function useGitConnections(organizationId?: string | null, ownerId?: string | null) {
  const scope = { organizationId, ownerId };
  return useQuery({
    queryKey: [...settingsKeys.git, ...scopeKey(scope)],
    queryFn: () => api.listGitConnections(scope),
  });
}

export function useBoardConnections(organizationId?: string | null, ownerId?: string | null) {
  const scope = { organizationId, ownerId };
  return useQuery({
    queryKey: [...settingsKeys.boards, ...scopeKey(scope)],
    queryFn: () => api.listBoardConnections(scope),
  });
}

export function useProjects() {
  return useQuery({
    queryKey: settingsKeys.projects,
    queryFn: api.listProjects,
    // The dashboard cards follow runs in progress.
    refetchInterval: (query) =>
      query.state.data?.items.some((p) => p.last_run && isRunActive(p.last_run)) ? POLL_MS : false,
  });
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: settingsKeys.project(id ?? ''),
    queryFn: () => api.getProject(id ?? ''),
    enabled: Boolean(id),
  });
}

export function useSaveGitConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: GitConnectionInput }) =>
      id ? api.updateGitConnection(id, body) : api.createGitConnection(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.git }),
  });
}

export function useDeleteGitConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.deleteGitConnection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.git }),
  });
}

export function useTestGitConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.testGitConnection,
    // The test records last_test_ok on the connection.
    onSettled: () => queryClient.invalidateQueries({ queryKey: settingsKeys.git }),
  });
}

export function useSaveBoardConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: BoardConnectionInput }) =>
      id ? api.updateBoardConnection(id, body) : api.createBoardConnection(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.boards }),
  });
}

export function useDeleteBoardConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.deleteBoardConnection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.boards }),
  });
}

export function useTestBoardConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.testBoardConnection,
    onSettled: () => queryClient.invalidateQueries({ queryKey: settingsKeys.boards }),
  });
}

export function useSaveProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: ProjectInput }) =>
      id ? api.updateProject(id, body) : api.createProject(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.projects }),
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.deleteProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: settingsKeys.projects }),
  });
}
