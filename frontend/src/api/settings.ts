import { apiRequest } from './client';
import type {
  BoardConnection,
  BoardConnectionInput,
  BoardTestResult,
  GitConnection,
  GitConnectionInput,
  GitTestResult,
  Page,
  PatternTestResponse,
  Project,
  ProjectInput,
  User,
  UserUpdate,
} from './types';

// Settings lists are small; one page of the maximum size holds them.
const ALL = '?page_size=100';

/** Whose connections: yours by default, an organization's, or (administrators) a user's. */
export interface ConnectionScope {
  organizationId?: string | null;
  ownerId?: string | null;
}

const scopeQuery = ({ organizationId, ownerId }: ConnectionScope = {}) =>
  organizationId ? `&organization_id=${organizationId}` : ownerId ? `&owner_id=${ownerId}` : '';

export const listGitConnections = (scope?: ConnectionScope) =>
  apiRequest<Page<GitConnection>>(`/git-connections${ALL}${scopeQuery(scope)}`);
export const createGitConnection = (body: GitConnectionInput) =>
  apiRequest<GitConnection>('/git-connections', { method: 'POST', body });
export const updateGitConnection = (id: string, body: Partial<GitConnectionInput>) =>
  apiRequest<GitConnection>(`/git-connections/${id}`, { method: 'PATCH', body });
export const deleteGitConnection = (id: string) =>
  apiRequest<void>(`/git-connections/${id}`, { method: 'DELETE' });
export const testGitConnection = (id: string) =>
  apiRequest<GitTestResult>(`/git-connections/${id}/test`, { method: 'POST' });

export const listBoardConnections = (scope?: ConnectionScope) =>
  apiRequest<Page<BoardConnection>>(`/board-connections${ALL}${scopeQuery(scope)}`);
export const createBoardConnection = (body: BoardConnectionInput) =>
  apiRequest<BoardConnection>('/board-connections', { method: 'POST', body });
export const updateBoardConnection = (id: string, body: Partial<BoardConnectionInput>) =>
  apiRequest<BoardConnection>(`/board-connections/${id}`, { method: 'PATCH', body });
export const deleteBoardConnection = (id: string) =>
  apiRequest<void>(`/board-connections/${id}`, { method: 'DELETE' });
export const testBoardConnection = (id: string) =>
  apiRequest<BoardTestResult>(`/board-connections/${id}/test`, { method: 'POST' });

export const listProjects = () => apiRequest<Page<Project>>(`/projects${ALL}`);
export const getProject = (id: string) => apiRequest<Project>(`/projects/${id}`);
export const createProject = (body: ProjectInput) =>
  apiRequest<Project>('/projects', { method: 'POST', body });
export const updateProject = (id: string, body: Partial<ProjectInput>) =>
  apiRequest<Project>(`/projects/${id}`, { method: 'PATCH', body });
export const deleteProject = (id: string) =>
  apiRequest<void>(`/projects/${id}`, { method: 'DELETE' });

export const testPattern = (pattern: string, samples: string[], signal?: AbortSignal) =>
  apiRequest<PatternTestResponse>('/projects/test-pattern', {
    method: 'POST',
    body: { pattern, samples },
    signal,
  });

export const updateMe = (body: UserUpdate) => apiRequest<User>('/me', { method: 'PATCH', body });
