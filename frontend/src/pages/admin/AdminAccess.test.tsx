import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AdminAzureConnection, AdminGitConnection, AdminProject } from '../../api/admin';
import type { Project } from '../../api/types';
import { useAuth } from '../../hooks/useAuth';
import { OWN_PROJECT, authValue, jsonResponse, mockFetch, renderWithProviders } from '../../test/utils';
import { ProjectDetailPage } from '../ProjectDetailPage';
import { ProjectWizardPage } from '../settings/ProjectWizardPage';
import { AdminConnectionsPage } from './AdminConnectionsPage';
import { AdminProjectsPage } from './AdminProjectsPage';

vi.mock('../../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue())); // the test user is an admin
afterEach(() => vi.unstubAllGlobals());

const bob = { id: 'u2', display_name: 'Bob', email: 'bob@example.com' };
const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 100 });

const bobsProject: Project = {
  id: 'p1',
  name: 'Billing',
  git_connection_id: 'g1',
  azure_connection_id: 'a1',
  branches: [],
  ticket_pattern: 'AB#(\\d+)',
  comment_template: '{subject} tt:{sha}',
  start_from: null,
  include_merge_commits: false,
  schedule_cron: null,
  schedule_enabled: false,
  dry_run_default: false,
  created_at: '',
  updated_at: '',
  last_run: null,
  next_run_at: null,
  comments_posted: 0,
  ...OWN_PROJECT,
  owner: bob,
  admin_access: true,
};

describe('administrator access', () => {
  it("opens anyone's project from Admin → Projects", async () => {
    const listed: AdminProject = {
      id: 'p1',
      name: 'Billing',
      owner: { ...bob, is_active: true },
      organization: null,
      shares: 0,
      created_at: '',
      last_run: null,
    };
    mockFetch({
      'GET /api/v1/admin/projects?page=1&page_size=50': () => page([listed]),
      'GET /api/v1/admin/transfers?page=1&page_size=20': () => page([]),
    });
    renderWithProviders(<AdminProjectsPage />);
    const link = await screen.findByRole('link', { name: 'Billing' });
    expect(link).toHaveAttribute('href', '/projects/p1');
  });

  it("warns on someone else's project and shows every action", async () => {
    mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse(bobsProject),
      'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page([]),
      'GET /api/v1/organizations': () => jsonResponse([]),
    });
    renderWithProviders(
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>,
      { route: '/projects/p1' },
    );
    expect(await screen.findByText('Administrator access')).toBeInTheDocument();
    expect(screen.getByText(/belongs to Bob/)).toBeInTheDocument();
    for (const name of ['Share', 'Sync now', 'Dry run']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument();
  });

  it("offers the owner's connections when editing their project", async () => {
    mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse(bobsProject),
      'GET /api/v1/organizations': () => jsonResponse([]),
      'GET /api/v1/git-connections?page_size=100&owner_id=u2': () =>
        page([{ id: 'g1', name: "Bob's repo", repo_url: 'https://github.com/bob/app', commit_url_pattern: '' }]),
      'GET /api/v1/azure-connections?page_size=100&owner_id=u2': () => page([]),
    });
    renderWithProviders(
      <Routes>
        <Route path="/settings/projects/:projectId" element={<ProjectWizardPage />} />
      </Routes>,
      { route: '/settings/projects/p1' },
    );
    const select = await screen.findByRole('textbox', { name: 'Git connection' });
    expect(select).toBeEnabled();
    await vi.waitFor(() => expect(select).toHaveValue("Bob's repo"));
  });

  it('lists every connection with its owner and edits one', async () => {
    const git = {
      id: 'g1',
      name: "Bob's repo",
      organization_id: null,
      repo_url: 'https://github.com/bob/app',
      auth_type: 'token',
      username: 'x-access-token',
      has_secret: true,
      commit_url_template: null,
      commit_url_pattern: '',
      host: 'github',
      last_test_at: null,
      last_test_ok: null,
      created_at: '',
      updated_at: '',
      owner: { ...bob, is_active: true },
      organization: null,
      projects: 2,
    } as AdminGitConnection;
    const azure = {
      id: 'a1',
      name: 'Acme board',
      organization_id: 'o1',
      organization_url: 'https://dev.azure.com/acme',
      azure_project: 'Web',
      has_secret: true,
      last_test_at: null,
      last_test_ok: null,
      created_at: '',
      updated_at: '',
      owner: null,
      organization: { id: 'o1', name: 'Acme' },
      projects: 0,
    } as AdminAzureConnection;
    mockFetch({
      'GET /api/v1/admin/git-connections?page=1&page_size=100': () => page([git]),
      'GET /api/v1/admin/azure-connections?page=1&page_size=100': () => page([azure]),
    });
    renderWithProviders(<AdminConnectionsPage />);
    const table = await screen.findByRole('table', { name: 'All connections' });
    expect(within(table).getByText('bob@example.com')).toBeInTheDocument();
    expect(within(table).getByText('Acme')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: "Edit Bob's repo" }));
    expect(await screen.findByRole('dialog', { name: 'Edit Git connection' })).toBeInTheDocument();
  });
});
