import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AzureConnection, GitConnection, Project, SyncRun, SyncRunDetail, SyncRunItem } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { authValue, errorResponse, jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { ProjectDetailPage } from './ProjectDetailPage';
import { RunDetailPage } from './RunDetailPage';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));

afterEach(() => vi.unstubAllGlobals());

const project = {
  id: 'p1',
  name: 'Web app',
  git_connection_id: 'g1',
  azure_connection_id: 'a1',
  branches: [],
} as unknown as Project;
const git = {
  id: 'g1',
  name: 'App repo',
  commit_url_pattern: 'https://github.com/acme/app/commit/{sha}',
} as GitConnection;
const azure = {
  id: 'a1',
  name: 'Board',
  organization_url: 'https://dev.azure.com/acme',
  azure_project: 'Web App',
} as AzureConnection;

const run: SyncRunDetail = {
  id: 'r1',
  project_id: 'p1',
  trigger: 'manual',
  dry_run: true,
  status: 'success',
  created_at: '2026-10-17T10:00:00Z',
  started_at: '2026-10-17T10:00:00Z',
  finished_at: '2026-10-17T10:00:04Z',
  commits_scanned: 3,
  comments_posted: 0,
  skipped: 0,
  errors: 0,
  error_message: null,
  cancel_requested: false,
  counts_by_action: { would_post: 2, no_reference: 1 },
};

const item = (overrides: Partial<SyncRunItem>): SyncRunItem => ({
  id: Math.random().toString(),
  commit_sha: 'abcdef1234567890abcdef1234567890abcdef12',
  commit_subject: 'Fix login AB#12',
  branch: 'main',
  work_item_id: 12,
  action: 'would_post',
  detail: null,
  ...overrides,
});

const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 50 });

function baseRoutes(extra: Record<string, Parameters<typeof mockFetch>[0][string]> = {}) {
  return mockFetch({
    'GET /api/v1/projects/p1': () => jsonResponse(project),
    'GET /api/v1/git-connections?page_size=100': () => page([git]),
    'GET /api/v1/azure-connections?page_size=100': () => page([azure]),
    ...extra,
  });
}

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/runs/:runId" element={<RunDetailPage />} />
    </Routes>,
    { route },
  );
}

describe('ProjectDetailPage', () => {
  it('lists the run history', async () => {
    baseRoutes({ 'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page<SyncRun>([run]) });
    renderAt('/projects/p1');
    expect(await screen.findByRole('heading', { name: 'Web app' })).toBeInTheDocument();
    expect(await screen.findByText('Success')).toBeInTheDocument();
    expect(screen.getByText('4 s')).toBeInTheDocument();
  });

  it('starts a dry run and opens it', async () => {
    const fetchMock = baseRoutes({
      'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page<SyncRun>([]),
      'POST /api/v1/projects/p1/sync': () => jsonResponse({ run_id: 'r1' }, 202),
      'GET /api/v1/runs/r1': () => jsonResponse(run),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([item({})]),
    });
    renderAt('/projects/p1');
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Dry run' }));

    expect(await screen.findByRole('heading', { name: 'Dry run' })).toBeInTheDocument();
    const sync = fetchMock.mock.calls.find(([url]) => url === '/api/v1/projects/p1/sync');
    expect(JSON.parse(String(sync?.[1]?.body))).toEqual({ dry_run: true });
  });
});

describe('deleting run history', () => {
  it('deletes one run after confirming', async () => {
    let runs: SyncRun[] = [run];
    const fetchMock = baseRoutes({
      'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page<SyncRun>(runs),
      'DELETE /api/v1/runs/r1': () => {
        runs = [];
        return new Response(null, { status: 204 });
      },
    });
    renderAt('/projects/p1');
    await userEvent.click(await screen.findByRole('button', { name: /^Delete run of/ }));
    expect(await screen.findByText(/never posted again/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/runs/r1' && init?.method === 'DELETE')).toBe(true);
  });

  it('clears all dry runs at once', async () => {
    const fetchMock = baseRoutes({
      'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page<SyncRun>([run]),
      'DELETE /api/v1/projects/p1/runs?dry_run=true': () => jsonResponse({ deleted: 1 }),
    });
    renderAt('/projects/p1');
    await userEvent.click(await screen.findByRole('button', { name: 'Clear dry runs' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/projects/p1/runs?dry_run=true')).toBe(true),
    );
  });
});

describe('RunDetailPage', () => {
  it('shows each commit with its work item and links', async () => {
    baseRoutes({
      'GET /api/v1/runs/r1': () => jsonResponse(run),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () =>
        page([
          item({}),
          item({ commit_subject: 'chore: deps', work_item_id: null, action: 'no_reference' }),
        ]),
    });
    renderAt('/projects/p1/runs/r1');

    const table = await screen.findByRole('table', { name: 'Run items' });
    expect(within(table).getByText('Fix login AB#12')).toBeInTheDocument();
    expect(within(table).getByRole('link', { name: '#12' })).toHaveAttribute(
      'href',
      'https://dev.azure.com/acme/Web%20App/_workitems/edit/12',
    );
    expect(within(table).getAllByRole('link', { name: 'abcdef1' })[0]).toHaveAttribute(
      'href',
      'https://github.com/acme/app/commit/abcdef1234567890abcdef1234567890abcdef12',
    );
    expect(within(table).getByText('No reference')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Would post (2)' })).toBeInTheDocument();
  });

  it('filters by action', async () => {
    const fetchMock = baseRoutes({
      'GET /api/v1/runs/r1': () => jsonResponse(run),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([item({})]),
      'GET /api/v1/runs/r1/items?page=1&page_size=50&action=no_reference': () =>
        page([item({ commit_subject: 'chore: deps', work_item_id: null, action: 'no_reference' })]),
    });
    renderAt('/projects/p1/runs/r1');
    await screen.findByRole('table', { name: 'Run items' });

    await userEvent.click(screen.getByRole('radio', { name: 'No reference (1)' }));
    expect(await screen.findByText('chore: deps')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('action=no_reference'))).toBe(true);
  });

  it('explains a failed run', async () => {
    baseRoutes({
      'GET /api/v1/runs/r1': () =>
        jsonResponse({ ...run, status: 'failed', error_message: 'Git authentication failed.' }),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([]),
    });
    renderAt('/projects/p1/runs/r1');
    expect(await screen.findByRole('alert')).toHaveTextContent('Git authentication failed.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('updates by itself while the run is in progress', async () => {
    const running = { ...run, status: 'running', finished_at: null };
    const answers = [running, { ...run, status: 'success' }];
    baseRoutes({
      'GET /api/v1/runs/r1': () => jsonResponse(answers.length > 1 ? answers.shift() : answers[0]),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([item({})]),
    });
    renderAt('/projects/p1/runs/r1');
    expect(await screen.findByText('The run is in progress')).toBeInTheDocument();
    expect(screen.getByText('This page updates by itself.')).toBeInTheDocument();
    // The next poll (2 s later) sees the run finished.
    expect(await screen.findByText('Success', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText('The run is in progress')).not.toBeInTheDocument();
  });

  it('cancels a running run after confirming', async () => {
    const running = { ...run, status: 'running', finished_at: null };
    let cancelled = false;
    const fetchMock = baseRoutes({
      'GET /api/v1/runs/r1': () => jsonResponse({ ...running, cancel_requested: cancelled }),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([]),
      'POST /api/v1/runs/r1/cancel': () => {
        cancelled = true;
        return jsonResponse({ ...running, cancel_requested: true }, 202);
      },
    });
    renderAt('/projects/p1/runs/r1');

    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(await screen.findByText(/Comments already posted stay/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel run' }));

    expect(await screen.findByText(/Cancelling: the run stops after the current commit/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/runs/r1/cancel')).toBe(true);
  });

  it('shows a cancelled run calmly', async () => {
    baseRoutes({
      'GET /api/v1/runs/r1': () =>
        jsonResponse({ ...run, status: 'cancelled', error_message: 'Cancelled by the user after 1 of 5 commits.' }),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page([item({ action: 'posted' })]),
    });
    renderAt('/projects/p1/runs/r1');
    expect(await screen.findByText('Cancelled by the user after 1 of 5 commits.')).toBeInTheDocument();
    expect(screen.getAllByText('Cancelled').length).toBeGreaterThan(0);
    expect(await screen.findByRole('table', { name: 'Run items' })).toBeInTheDocument();
  });

  it('reports a run that is not found', async () => {
    baseRoutes({
      'GET /api/v1/runs/r1': () => errorResponse(404, 'not_found', 'Run not found.'),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => errorResponse(404, 'not_found'),
    });
    renderAt('/projects/p1/runs/r1');
    expect(await screen.findByRole('alert')).toHaveTextContent('Run not found.');
  });
});
