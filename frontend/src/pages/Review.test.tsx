import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Project, SyncRunDetail, SyncRunItem } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { OWN_PROJECT, authValue, jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { RunDetailPage } from './RunDetailPage';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));
afterEach(() => vi.unstubAllGlobals());

const project = {
  id: 'p1',
  name: 'Web app',
  branches: [],
  ...OWN_PROJECT,
  git_connection: { id: 'g1', name: 'Repo', repo_url: '', host: 'github', commit_url_pattern: '' },
  board_connection: { id: 'a1', name: 'Board', kind: 'azure', url: 'https://dev.azure.com/acme', scope: 'Web' },
} as unknown as Project;

const dryRun: SyncRunDetail = {
  id: 'r1',
  project_id: 'p1',
  trigger: 'manual',
  dry_run: true,
  status: 'success',
  created_at: '2026-11-09T10:00:00Z',
  started_at: '2026-11-09T10:00:00Z',
  finished_at: '2026-11-09T10:00:03Z',
  commits_scanned: 2,
  comments_posted: 0,
  skipped: 0,
  errors: 0,
  error_message: null,
  cancel_requested: false,
  counts_by_action: { would_post: 1, no_reference: 1 },
};

const row = (overrides: Partial<SyncRunItem>): SyncRunItem => ({
  id: 'i1',
  commit_sha: 'abcdef1234567890abcdef1234567890abcdef12',
  commit_subject: 'Fix login AB#1',
  branch: 'main',
  work_item_id: '1',
  action: 'would_post',
  detail: null,
  manual: false,
  ...overrides,
});
const rows = [
  row({}),
  row({
    id: 'i2',
    commit_sha: '1234567aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    commit_subject: 'Refactor the cart',
    work_item_id: null,
    action: 'no_reference',
  }),
];
const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 50 });

function renderRun(route = '/projects/p1/runs/r1') {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:projectId/runs/:runId" element={<RunDetailPage />} />
    </Routes>,
    { route },
  );
}

const baseRoutes = (extra: Parameters<typeof mockFetch>[0] = {}) =>
  mockFetch({
    'GET /api/v1/projects/p1': () => jsonResponse(project),
    'GET /api/v1/runs/r1': () => jsonResponse(dryRun),
    'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page(rows),
    ...extra,
  });

describe('reviewing a dry run', () => {
  it('deselects a commit and posts the selection', async () => {
    const fetchMock = baseRoutes({
      'POST /api/v1/runs/r1/items/i1/exclude': () => jsonResponse(row({ action: 'excluded' })),
      'POST /api/v1/runs/r1/post': () => jsonResponse({ run_id: 'r2' }, 202),
      'GET /api/v1/runs/r2': () => jsonResponse({ ...dryRun, id: 'r2', dry_run: false, source_run_id: 'r1' }),
      'GET /api/v1/runs/r2/items?page=1&page_size=50': () => page([]),
    });
    renderRun();
    const post = await screen.findByRole('button', { name: 'Post selected (1)' });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Post abcdef1 to #1' }));
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/runs/r1/items/i1/exclude')).toBe(true),
    );
    // A row without a work item can't be selected until it gets one.
    expect(screen.getByRole('checkbox', { name: 'Post 1234567 to #?' })).toBeDisabled();

    await userEvent.click(post);
    const confirm = await screen.findByRole('dialog', { name: 'Post the selected commits?' });
    await userEvent.click(within(confirm).getByRole('button', { name: 'Post selected' }));
    expect(await screen.findByText(/Posts the selection of a/)).toBeInTheDocument();
  });

  it('picks a work item for a commit without one', async () => {
    const fetchMock = baseRoutes({
      'GET /api/v1/projects/p1/work-items?q=': () =>
        jsonResponse({
          ok: true,
          error: null,
          items: [
            { id: '5', title: 'Checkout redesign', type: 'User Story', state: 'New', closed: false },
            { id: '4', title: 'Old checkout', type: 'User Story', state: 'Closed', closed: true },
          ],
        }),
      'PUT /api/v1/runs/r1/items/i2/work-item': () =>
        jsonResponse(row({ id: 'i2', work_item_id: '5', manual: true })),
    });
    renderRun();
    await userEvent.click(await screen.findByRole('textbox', { name: 'Work item for 1234567' }));
    await userEvent.click(await screen.findByRole('option', { name: /#5 · Checkout redesign/ }));
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ work_item_id: '5' });
  });

  it('offers changing the work item of a row that has one', async () => {
    baseRoutes();
    renderRun();
    await userEvent.click(await screen.findByRole('button', { name: 'Change the work item of abcdef1' }));
    expect(await screen.findByRole('textbox', { name: 'Work item for abcdef1' })).toBeInTheDocument();
  });

  it('shows a viewer the dry run without the review', async () => {
    mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse({ ...project, role: 'viewer' }),
      'GET /api/v1/runs/r1': () => jsonResponse(dryRun),
      'GET /api/v1/runs/r1/items?page=1&page_size=50': () => page(rows),
    });
    renderRun();
    expect(await screen.findByText('Fix login AB#1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Post selected/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /Work item for/ })).not.toBeInTheDocument();
  });
});
