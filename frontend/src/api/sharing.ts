import { apiRequest } from './client';
import type { ProjectShare, ShareRole } from './types';

const base = (projectId: string) => `/projects/${projectId}/shares`;

export const listShares = (projectId: string) => apiRequest<ProjectShare[]>(base(projectId));

export const addShare = (projectId: string, email: string, role: ShareRole) =>
  apiRequest<ProjectShare>(base(projectId), { method: 'POST', body: { email, role } });

export const updateShare = (projectId: string, userId: string, role: ShareRole) =>
  apiRequest<ProjectShare>(`${base(projectId)}/${userId}`, { method: 'PATCH', body: { role } });

/** The owner removes someone, or a user leaves a project shared with them. */
export const removeShare = (projectId: string, userId: string) =>
  apiRequest<void>(`${base(projectId)}/${userId}`, { method: 'DELETE' });
