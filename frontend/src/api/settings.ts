import { apiRequest } from './client';
import type {
  AzureConnection,
  AzureConnectionInput,
  AzureTestResult,
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

export const listGitConnections = () => apiRequest<Page<GitConnection>>(`/git-connections${ALL}`);
export const createGitConnection = (body: GitConnectionInput) =>
  apiRequest<GitConnection>('/git-connections', { method: 'POST', body });
export const updateGitConnection = (id: string, body: Partial<GitConnectionInput>) =>
  apiRequest<GitConnection>(`/git-connections/${id}`, { method: 'PATCH', body });
export const deleteGitConnection = (id: string) =>
  apiRequest<void>(`/git-connections/${id}`, { method: 'DELETE' });
export const testGitConnection = (id: string) =>
  apiRequest<GitTestResult>(`/git-connections/${id}/test`, { method: 'POST' });

export const listAzureConnections = () =>
  apiRequest<Page<AzureConnection>>(`/azure-connections${ALL}`);
export const createAzureConnection = (body: AzureConnectionInput) =>
  apiRequest<AzureConnection>('/azure-connections', { method: 'POST', body });
export const updateAzureConnection = (id: string, body: Partial<AzureConnectionInput>) =>
  apiRequest<AzureConnection>(`/azure-connections/${id}`, { method: 'PATCH', body });
export const deleteAzureConnection = (id: string) =>
  apiRequest<void>(`/azure-connections/${id}`, { method: 'DELETE' });
export const testAzureConnection = (id: string) =>
  apiRequest<AzureTestResult>(`/azure-connections/${id}/test`, { method: 'POST' });

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
