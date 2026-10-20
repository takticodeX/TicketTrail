import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Project, ProjectShare, SyncRun, SyncRunDetail } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { canManageRun } from '../lib/access';
import { OWN_PROJECT, authValue, errorResponse, jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { DashboardPage } from './DashboardPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import { RunDetailPage } from './RunDetailPage';
import { ProjectWizardPage } from './settings/ProjectWizardPage';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));
afterEach(() => vi.unstubAllGlobals());

const olivia = { id: 'u9', display_name: 'Olivia', email: 'olivia@example.com' };
const alice = { id: 'u1', display_name: 'Alice', email: 'alice@example.com' };

const base: Project = {
  id: 'p1',
  name: 'Web app',
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
  git_connection: {
    id: 'g1',
    name: 'Olivia repo',
    repo_url: 'https://github.com/acme/app',
    host: 'github',
    commit_url_pattern: 'https://github.com/acme/app/commit/{sha}',
  },
  azure_connection: {
    id: 'a1',
    name: 'Olivia board',
    organization_url: 'https://dev.azure.com/acme',
    azure_project: 'Web',
  },
};
const sharedAs = (role: 'viewer' | 'editor'): Project => ({ ...base, role, owner: olivia });

const run = (overrides: Partial<SyncRun> = {}): SyncRunDetail => ({
  id: 'r1',
  project_id: 'p1',
  trigger: 'manual',
  dry_run: true,
  status: 'success',
  created_at: '2026-10-17T10:00:00Z',
  started_at: '2026-10-17T10:00:00Z',
  finished_at: '2026-10-17T10:00:04Z',
  commits_scanned: 1,
  comments_posted: 0,
  skipped: 0,
  errors: 0,
  error_message: null,
  cancel_requested: false,
  triggered_by: olivia,
  counts_by_action: {},
  ...overrides,
});

const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 50 });

function projectRoutes(project: Project, runs: SyncRun[] = [], extra: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    'GET /api/v1/projects/p1': () => jsonResponse(project),
    'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page(runs),
    ...extra,
  });
}

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/runs/:runId" element={<RunDetailPage />} />
      <Route path="/settings/projects/:projectId" element={<ProjectWizardPage />} />
    </Routes>,
    { route },
  );
}

describe('canManageRun', () => {
  it('lets editors manage every run and viewers only their own dry runs', () => {
    expect(canManageRun({ role: 'editor' }, run({ dry_run: false }), 'u1')).toBe(true);
    expect(canManageRun({ role: 'viewer' }, run({ triggered_by: alice }), 'u1')).toBe(true);
    expect(canManageRun({ role: 'viewer' }, run(), 'u1')).toBe(false);
    expect(canManageRun({ role: 'viewer' }, run({ dry_run: false, triggered_by: alice }), 'u1')).toBe(false);
  });
});

describe('a project shared with you', () => {
  it('shows a viewer the project without the editing buttons', async () => {
    projectRoutes(sharedAs('viewer'), [run()]);
    renderAt('/projects/p1');
    expect(await screen.findByRole('heading', { name: 'Web app' })).toBeInTheDocument();
    expect(screen.getByText('Viewer')).toBeInTheDocument();
    expect(screen.getByText('Shared with you by Olivia')).toBeInTheDocument();
    // The connections come with the project: a shared user can't list the owner's.
    expect(screen.getByText(/Olivia repo/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dry run' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Leave' })).toBeInTheDocument();
    for (const name of ['Sync now', 'Share', 'Clear dry runs']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
    expect(await screen.findByText('by Olivia')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Delete run of/ })).not.toBeInTheDocument();
  });

  it('lets a viewer delete the dry runs they started', async () => {
    projectRoutes(sharedAs('viewer'), [run({ triggered_by: alice })]);
    renderAt('/projects/p1');
    expect(await screen.findByRole('button', { name: /^Delete run of/ })).toBeInTheDocument();
  });

  it('gives an editor Sync now and Settings, but not Share', async () => {
    projectRoutes(sharedAs('editor'));
    renderAt('/projects/p1');
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument();
  });

  it('leaves the project after confirming', async () => {
    const fetchMock = projectRoutes(sharedAs('viewer'), [], {
      'DELETE /api/v1/projects/p1/shares/u1': () => new Response(null, { status: 204 }),
      'GET /api/v1/projects?page_size=100': () => page<Project>([]),
    });
    renderAt('/projects/p1');
    await userEvent.click(await screen.findByRole('button', { name: 'Leave' }));
    const confirm = await screen.findByRole('dialog', { name: 'Leave this project?' });
    await userEvent.click(within(confirm).getByRole('button', { name: 'Leave' }));
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true);
  });

  it('hides Cancel and Delete on a run page for a viewer who did not start it', async () => {
    projectRoutes(sharedAs('viewer'), [], {
      'GET /api/v1/runs/r1': () => jsonResponse(run({ status: 'running', finished_at: null })),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([]),
    });
    renderAt('/projects/p1/runs/r1');
    expect(await screen.findByText('The run is in progress')).toBeInTheDocument();
    expect(screen.getByText(/by Olivia/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('locks the connections for an editor in the settings', async () => {
    mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse(sharedAs('editor')),
      'GET /api/v1/git-connections?page_size=100': () => page([]),
      'GET /api/v1/azure-connections?page_size=100': () => page([]),
    });
    renderAt('/settings/projects/p1');
    const select = await screen.findByRole('textbox', { name: 'Git connection' });
    expect(select).toBeDisabled();
    expect(select).toHaveValue('Olivia repo');
    expect(screen.getAllByText('Only Olivia can change the connection.').length).toBeGreaterThan(0);
    expect(screen.queryByText(/No Git connections yet/)).not.toBeInTheDocument();
  });

  it('tells a viewer the settings are for editors', async () => {
    mockFetch({ 'GET /api/v1/projects/p1': () => jsonResponse(sharedAs('viewer')) });
    renderAt('/settings/projects/p1');
    expect(await screen.findByText(/Only an editor can change/)).toBeInTheDocument();
  });

  it('shows shared projects in their own dashboard section', async () => {
    mockFetch({
      'GET /api/v1/projects?page_size=100': () =>
        page([{ ...base, id: 'p0', name: 'Mine' }, { ...sharedAs('viewer'), name: 'Theirs' }]),
    });
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Shared with me' })).toBeInTheDocument();
    const mine = screen.getByLabelText('Mine');
    const theirs = screen.getByLabelText('Theirs');
    expect(within(mine).getByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(within(theirs).queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
    expect(within(theirs).getByText('Viewer')).toBeInTheDocument();
    expect(within(theirs).getByText('Shared with you by Olivia')).toBeInTheDocument();
  });
});

describe('sharing your project', () => {
  const bob: ProjectShare = {
    user: { id: 'u2', display_name: 'Bob', email: 'bob@example.com' },
    role: 'viewer',
    created_at: '',
  };

  it('adds, changes and lists shares', async () => {
    let shares: ProjectShare[] = [];
    const fetchMock = projectRoutes({ ...base, shares: 0 }, [], {
      'GET /api/v1/projects/p1/shares': () => jsonResponse(shares),
      'POST /api/v1/projects/p1/shares': (_url, init) => {
        shares = [{ ...bob, role: JSON.parse(String(init?.body)).role }];
        return jsonResponse(shares[0], 201);
      },
      'PATCH /api/v1/projects/p1/shares/u2': (_url, init) => {
        shares = [{ ...bob, role: JSON.parse(String(init?.body)).role }];
        return jsonResponse(shares[0]);
      },
      'GET /api/v1/projects?page_size=100': () => page([base]),
    });
    renderAt('/projects/p1');
    await userEvent.click(await screen.findByRole('button', { name: 'Share' }));
    const drawer = await screen.findByRole('dialog', { name: 'Share "Web app"' });
    expect(await within(drawer).findByText('Not shared with anyone yet.')).toBeInTheDocument();
    await userEvent.type(within(drawer).getByRole('textbox', { name: 'Email' }), 'bob@example.com');
    await userEvent.click(within(drawer).getByRole('button', { name: 'Share' }));

    const list = await within(drawer).findByRole('table', { name: 'Shared with' });
    expect(within(list).getByText('bob@example.com')).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ email: 'bob@example.com', role: 'viewer' });

    await userEvent.click(within(list).getByRole('textbox', { name: 'Role of bob@example.com' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Editor' }));
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ role: 'editor' });
  });

  it('shows why a share failed', async () => {
    projectRoutes(base, [], {
      'GET /api/v1/projects/p1/shares': () => jsonResponse([]),
      'POST /api/v1/projects/p1/shares': () => errorResponse(404, 'user_not_found', 'No user with this email.'),
    });
    renderAt('/projects/p1');
    await userEvent.click(await screen.findByRole('button', { name: 'Share' }));
    const drawer = await screen.findByRole('dialog', { name: 'Share "Web app"' });
    await userEvent.type(within(drawer).getByRole('textbox', { name: 'Email' }), 'nobody@example.com');
    await userEvent.click(within(drawer).getByRole('button', { name: 'Share' }));
    expect(await within(drawer).findByText('No user with this email.')).toBeInTheDocument();
  });
});
