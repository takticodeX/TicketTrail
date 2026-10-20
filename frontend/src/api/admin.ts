import { apiRequest } from './client';
import type { Page, SyncRun, User, UserSummary } from './types';

export interface AdminUser extends User {
  projects: number;
}

export interface AdminProject {
  id: string;
  name: string;
  owner: UserSummary & { is_active: boolean };
  shares: number;
  created_at: string;
  last_run: SyncRun | null;
}

export interface OwnershipTransfer {
  id: string;
  created_at: string;
  admin: UserSummary | null;
  from_user: UserSummary | null;
  to_user: UserSummary | null;
  /** Null when everything the user owned was moved. */
  project_id: string | null;
  projects_moved: number;
  connections_moved: number;
  /** Connections still used by the previous owner's other projects are copied. */
  connections_copied: number;
  summary: string;
}

export const listUsers = (page: number, pageSize = 50) =>
  apiRequest<Page<AdminUser>>(`/admin/users?page=${page}&page_size=${pageSize}`);

export const setUserActive = (userId: string, isActive: boolean) =>
  apiRequest<AdminUser>(`/admin/users/${userId}`, { method: 'PATCH', body: { is_active: isActive } });

export const listAllProjects = (page: number, pageSize = 50) =>
  apiRequest<Page<AdminProject>>(`/admin/projects?page=${page}&page_size=${pageSize}`);

export const transferProject = (projectId: string, toUserId: string) =>
  apiRequest<OwnershipTransfer>(`/admin/projects/${projectId}/transfer`, {
    method: 'POST',
    body: { to_user_id: toUserId },
  });

export const transferEverything = (userId: string, toUserId: string) =>
  apiRequest<OwnershipTransfer>(`/admin/users/${userId}/transfer`, {
    method: 'POST',
    body: { to_user_id: toUserId },
  });

export const listTransfers = (page: number, pageSize = 20) =>
  apiRequest<Page<OwnershipTransfer>>(`/admin/transfers?page=${page}&page_size=${pageSize}`);
