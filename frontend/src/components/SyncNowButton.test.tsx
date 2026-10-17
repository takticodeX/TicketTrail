import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Project, SyncRun } from '../api/types';
import { jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { SyncNowButton } from './SyncNowButton';

afterEach(() => vi.unstubAllGlobals());

const project = { id: 'p1', name: 'Web app', start_from: null } as unknown as Project;
const dryRun = {
  id: 'r0',
  dry_run: true,
  status: 'success',
  created_at: '2026-10-17T09:00:00Z',
  started_at: '2026-10-17T09:00:00Z',
} as SyncRun;
const RUNS = 'GET /api/v1/projects/p1/runs?page=1&page_size=20';
const page = (items: SyncRun[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 20 });

function renderButton(onDryRun = vi.fn()) {
  renderWithProviders(
    <Routes>
      <Route path="/" element={<SyncNowButton project={project} onDryRun={onDryRun} />} />
      <Route path="/projects/p1/runs/:runId" element={<p>run page</p>} />
    </Routes>,
  );
  return onDryRun;
}

const posts = (fetchMock: ReturnType<typeof mockFetch>) =>
  fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/projects/p1/sync' && init?.method === 'POST');

describe('SyncNowButton', () => {
  it("asks first, with the last dry run's numbers, then posts", async () => {
    const fetchMock = mockFetch({
      [RUNS]: () => page([dryRun]),
      'GET /api/v1/runs/r0': () =>
        jsonResponse({ ...dryRun, counts_by_action: { would_post: 7, skipped_not_found: 2 } }),
      'POST /api/v1/projects/p1/sync': () => jsonResponse({ run_id: 'r1' }, 202),
    });
    renderButton();

    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('7 comments')).toBeInTheDocument();
    expect(screen.getByText(/2 references point to work items that don't exist/)).toBeInTheDocument();
    expect(posts(fetchMock)).toHaveLength(0);

    await userEvent.click(screen.getByRole('button', { name: 'Post comments' }));
    expect(await screen.findByText('run page')).toBeInTheDocument();
    expect(JSON.parse(String(posts(fetchMock)[0]?.[1]?.body))).toEqual({ dry_run: false });
  });

  it('warns when there is no dry run and offers one', async () => {
    const fetchMock = mockFetch({ [RUNS]: () => page([]) });
    const onDryRun = renderButton();

    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('There is no dry run yet.')).toBeInTheDocument();
    expect(screen.getByText(/in the whole history/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Dry run first' }));
    expect(onDryRun).toHaveBeenCalledOnce();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it('can be cancelled', async () => {
    const fetchMock = mockFetch({ [RUNS]: () => page([]) });
    renderButton();
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(posts(fetchMock)).toHaveLength(0);
  });
});
