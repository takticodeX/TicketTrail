import { apiRequest } from './client';
import type {
  AzureConnection,
  GitConnection,
  OrganizationMember,
  OrganizationSummary,
  Page,
  SyncRun,
  User,
  UserSummary,
} from './types';

export interface AdminUser extends User {
  projects: number;
}

export interface AdminProject {
  id: string;
  name: string;
  /** Null for an organization's project. */
  owner: (UserSummary & { is_active: boolean }) | null;
  organization: OrganizationSummary | null;
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

export interface AdminOrganization extends OrganizationSummary {
  timezone: string;
  members: number;
  admins: UserSummary[];
  people: OrganizationMember[];
  projects: number;
  connections: number;
  created_at: string;
}

export const listAllOrganizations = (page: number, pageSize = 50) =>
  apiRequest<Page<AdminOrganization>>(`/admin/organizations?page=${page}&page_size=${pageSize}`);

/** Make a member an admin of the organization, for one left without an admin. */
export const promoteAdmin = (organizationId: string, userId: string) =>
  apiRequest<AdminOrganization>(`/admin/organizations/${organizationId}/admins`, {
    method: 'POST',
    body: { user_id: userId },
  });

/** Who owns a connection, in the administrator's list. */
export interface ConnectionOwner {
  owner: (UserSummary & { is_active: boolean }) | null;
  organization: OrganizationSummary | null;
  /** Number of projects that use it. */
  projects: number;
}

export type AdminGitConnection = GitConnection & ConnectionOwner;
export type AdminAzureConnection = AzureConnection & ConnectionOwner;

export const listAllGitConnections = (page: number, pageSize = 100) =>
  apiRequest<Page<AdminGitConnection>>(`/admin/git-connections?page=${page}&page_size=${pageSize}`);

export const listAllAzureConnections = (page: number, pageSize = 100) =>
  apiRequest<Page<AdminAzureConnection>>(`/admin/azure-connections?page=${page}&page_size=${pageSize}`);

/** An administrator's action on someone else's data. */
export interface AuditEvent {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_email: string;
  /** A verb such as "update", "delete", "sync" or "share". */
  action: string;
  resource_type: 'project' | 'run' | 'git_connection' | 'azure_connection' | 'organization';
  resource_id: string | null;
  resource_name: string;
  /** Whose it is: an email, or "organization <name>". */
  owner_label: string;
}

export const listActivity = (page: number, pageSize = 50) =>
  apiRequest<Page<AuditEvent>>(`/admin/activity?page=${page}&page_size=${pageSize}`);

export const listTransfers = (page: number, pageSize = 20) =>
  apiRequest<Page<OwnershipTransfer>>(`/admin/transfers?page=${page}&page_size=${pageSize}`);
