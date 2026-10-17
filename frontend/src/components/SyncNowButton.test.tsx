import { ModalsProvider } from '@mantine/modals';
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

function renderButton(runs: SyncRun[], onDryRun = vi.fn()) {
  renderWithProviders(
    <ModalsProvider>
      <Routes>
        <Route path="/" element={<SyncNowButton project={project} runs={runs} onDryRun={onDryRun} />} />
        <Route path="/projects/p1/runs/:runId" element={<p>run page</p>} />
      </Routes>
    </ModalsProvider>,
  );
  return onDryRun;
}

describe('SyncNowButton', () => {
  it("asks first, with the last dry run's numbers, then posts", async () => {
    const fetchMock = mockFetch({
      'GET /api/v1/runs/r0': () =>
        jsonResponse({ ...dryRun, counts_by_action: { would_post: 7, skipped_not_found: 2 } }),
      'POST /api/v1/projects/p1/sync': () => jsonResponse({ run_id: 'r1' }, 202),
    });
    renderButton([dryRun]);

    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('7 comments')).toBeInTheDocument();
    expect(screen.getByText(/2 references point to work items that don't exist/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/projects/p1/sync')).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: 'Post comments' }));
    expect(await screen.findByText('run page')).toBeInTheDocument();
    const sync = fetchMock.mock.calls.find(([url]) => url === '/api/v1/projects/p1/sync');
    expect(JSON.parse(String(sync?.[1]?.body))).toEqual({ dry_run: false });
  });

  it('warns when there is no dry run and offers one', async () => {
    const fetchMock = mockFetch({});
    const onDryRun = renderButton([]);

    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(await screen.findByText('There is no dry run yet.')).toBeInTheDocument();
    expect(screen.getByText(/in the whole history/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Dry run first' }));
    expect(onDryRun).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('can be cancelled', async () => {
    const fetchMock = mockFetch({});
    renderButton([]);
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
