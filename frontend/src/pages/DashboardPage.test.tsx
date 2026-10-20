import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Project, SyncRun } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { OWN_PROJECT, authValue, jsonResponse, mockFetch, renderWithProviders, testUser } from '../test/utils';
import { DashboardPage } from './DashboardPage';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue({ user: { ...testUser, timezone: 'Europe/Rome' } })));
afterEach(() => vi.unstubAllGlobals());

const lastRun = {
  id: 'r9',
  status: 'partial',
  dry_run: false,
  created_at: '2026-10-17T08:00:00Z',
  started_at: '2026-10-17T08:00:00Z',
} as SyncRun;

const scheduled = {
  id: 'p1',
  name: 'Web app',
  branches: [],
  last_run: lastRun,
  next_run_at: '2026-10-19T06:00:00Z', // Monday 08:00 in Rome
  comments_posted: 42,
  ...OWN_PROJECT,
} as unknown as Project;

const manual = {
  id: 'p2',
  name: 'Docs',
  branches: [],
  last_run: null,
  next_run_at: null,
  comments_posted: 1,
  ...OWN_PROJECT,
} as unknown as Project;

const projects = (items: Project[]) =>
  jsonResponse({ items, total: items.length, page: 1, page_size: 100 });

function renderDashboard() {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/projects/:projectId/runs/:runId" element={<p>run page</p>} />
    </Routes>,
  );
}

describe('DashboardPage', () => {
  it('shows one card per project with its status', async () => {
    mockFetch({ 'GET /api/v1/projects?page_size=100': () => projects([scheduled, manual]) });
    renderDashboard();

    const card = await screen.findByLabelText('Web app');
    expect(within(card).getByText('Partial')).toBeInTheDocument();
    // 06:00 UTC shown in the user's time zone (Rome): 08:00. The date format follows the locale.
    expect(within(card).getByText(/^Next run: .*08:00$/)).toBeInTheDocument();
    expect(within(card).getByText('42 comments posted')).toBeInTheDocument();

    const other = screen.getByLabelText('Docs');
    expect(within(other).getByText('Never run')).toBeInTheDocument();
    expect(within(other).getByText('No schedule: manual only')).toBeInTheDocument();
    expect(within(other).getByText('1 comment posted')).toBeInTheDocument();
  });

  it('starts a dry run from a card', async () => {
    const fetchMock = mockFetch({
      'GET /api/v1/projects?page_size=100': () => projects([manual]),
      'POST /api/v1/projects/p2/sync': () => jsonResponse({ run_id: 'r1' }, 202),
    });
    renderDashboard();
    const card = await screen.findByLabelText('Docs');
    await userEvent.click(within(card).getByRole('button', { name: 'Dry run' }));

    expect(await screen.findByText('run page')).toBeInTheDocument();
    const sync = fetchMock.mock.calls.find(([url]) => url === '/api/v1/projects/p2/sync');
    expect(JSON.parse(String(sync?.[1]?.body))).toEqual({ dry_run: true });
  });

  it('invites to create the first project', async () => {
    mockFetch({ 'GET /api/v1/projects?page_size=100': () => projects([]) });
    renderDashboard();
    expect(await screen.findByRole('link', { name: 'Create a project' })).toBeInTheDocument();
  });
});
