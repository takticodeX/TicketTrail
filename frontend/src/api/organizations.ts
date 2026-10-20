import { apiRequest } from './client';
import type { Organization, OrganizationMember, OrganizationRole, ProjectMoved } from './types';

const base = (id: string) => `/organizations/${id}`;

export const listOrganizations = () => apiRequest<Organization[]>('/organizations');
export const getOrganization = (id: string) => apiRequest<Organization>(base(id));
export const createOrganization = (body: { name: string; timezone?: string }) =>
  apiRequest<Organization>('/organizations', { method: 'POST', body });
export const updateOrganization = (id: string, body: { name?: string; timezone?: string }) =>
  apiRequest<Organization>(base(id), { method: 'PATCH', body });
export const deleteOrganization = (id: string) => apiRequest<void>(base(id), { method: 'DELETE' });

export const listMembers = (id: string) => apiRequest<OrganizationMember[]>(`${base(id)}/members`);
export const addMember = (id: string, email: string, role: OrganizationRole) =>
  apiRequest<OrganizationMember>(`${base(id)}/members`, { method: 'POST', body: { email, role } });
export const updateMember = (id: string, userId: string, role: OrganizationRole) =>
  apiRequest<OrganizationMember>(`${base(id)}/members/${userId}`, { method: 'PATCH', body: { role } });
/** Admins remove a member; anyone can leave. */
export const removeMember = (id: string, userId: string) =>
  apiRequest<void>(`${base(id)}/members/${userId}`, { method: 'DELETE' });

/** Into an organization (the personal owner), or out of it to a member (its admins). */
export const moveProject = (projectId: string, target: { organization_id: string } | { to_user_id: string }) =>
  apiRequest<ProjectMoved>(`/projects/${projectId}/move`, { method: 'POST', body: target });
