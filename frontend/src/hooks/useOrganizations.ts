import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as api from '../api/organizations';
import type { OrganizationRole } from '../api/types';
import { settingsKeys } from './useSettings';

export const organizationKeys = {
  all: ['organizations'] as const,
  one: (id: string) => ['organizations', id] as const,
  members: (id: string) => ['organizations', id, 'members'] as const,
};

export function useOrganizations() {
  return useQuery({ queryKey: organizationKeys.all, queryFn: api.listOrganizations });
}

export function useOrganization(id: string) {
  return useQuery({ queryKey: organizationKeys.one(id), queryFn: () => api.getOrganization(id) });
}

export function useMembers(id: string | undefined) {
  return useQuery({
    queryKey: organizationKeys.members(id ?? ''),
    queryFn: () => api.listMembers(id ?? ''),
    enabled: Boolean(id),
  });
}

function useOrganizationMutation<T, R>(mutationFn: (args: T) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    // Member counts, roles and the projects people see all follow.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: organizationKeys.all });
      void queryClient.invalidateQueries({ queryKey: settingsKeys.projects });
    },
  });
}

export const useCreateOrganization = () => useOrganizationMutation(api.createOrganization);

export const useUpdateOrganization = (id: string) =>
  useOrganizationMutation((body: { name?: string; timezone?: string }) => api.updateOrganization(id, body));

export const useDeleteOrganization = () => useOrganizationMutation(api.deleteOrganization);

export const useAddMember = (id: string) =>
  useOrganizationMutation(({ email, role }: { email: string; role: OrganizationRole }) =>
    api.addMember(id, email, role),
  );

export const useUpdateMember = (id: string) =>
  useOrganizationMutation(({ userId, role }: { userId: string; role: OrganizationRole }) =>
    api.updateMember(id, userId, role),
  );

export const useRemoveMember = (id: string) =>
  useOrganizationMutation((userId: string) => api.removeMember(id, userId));

export function useMoveProject(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (target: { organization_id: string } | { to_user_id: string }) =>
      api.moveProject(projectId, target),
    onSuccess: () => {
      for (const key of [settingsKeys.projects, settingsKeys.git, settingsKeys.azure, organizationKeys.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
