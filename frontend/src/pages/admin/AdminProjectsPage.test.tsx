import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AdminProject, AdminUser, OwnershipTransfer } from '../../api/admin';
import { useAuth } from '../../hooks/useAuth';
import { authValue, jsonResponse, mockFetch, renderWithProviders, testUser } from '../../test/utils';
import { AdminProjectsPage } from './AdminProjectsPage';
import { AdminUsersPage } from './AdminUsersPage';

vi.mock('../../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));
afterEach(() => vi.unstubAllGlobals());

const marco: AdminUser = {
  ...testUser,
  id: 'u2',
  email: 'marco@example.com',
  display_name: 'Marco',
  role: 'user',
  is_active: false,
  projects: 1,
};
const anna: AdminUser = { ...marco, id: 'u3', email: 'anna@example.com', display_name: 'Anna', is_active: true };
const billing: AdminProject = {
  id: 'p1',
  name: 'Billing',
  owner: { id: 'u2', display_name: 'Marco', email: 'marco@example.com', is_active: false },
  shares: 2,
  created_at: '',
  last_run: null,
};
const done: OwnershipTransfer = {
  id: 't1',
  created_at: '2026-10-20T10:00:00Z',
  admin: { id: 'u1', display_name: 'Alice', email: 'alice@example.com' },
  from_user: marco,
  to_user: anna,
  project_id: 'p1',
  projects_moved: 1,
  connections_moved: 2,
  connections_copied: 0,
  summary: 'Project "Billing" from marco@example.com to anna@example.com',
};
const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 50 });

async function pickNewOwner(name: string) {
  const dialog = await screen.findByRole('dialog');
  await userEvent.click(within(dialog).getByRole('textbox', { name: 'New owner' }));
  await userEvent.click(await screen.findByRole('option', { name }));
  await userEvent.click(within(dialog).getByRole('button', { name: 'Transfer' }));
}

describe('AdminProjectsPage', () => {
  it('lists every project with its owner and transfers one', async () => {
    let transfers: OwnershipTransfer[] = [];
    const fetchMock = mockFetch({
      'GET /api/v1/admin/projects?page=1&page_size=50': () => page([billing]),
      'GET /api/v1/admin/transfers?page=1&page_size=20': () => page(transfers),
      'GET /api/v1/admin/users?page=1&page_size=100': () => page([testUser, marco, anna]),
      'POST /api/v1/admin/projects/p1/transfer': () => {
        transfers = [done];
        return jsonResponse(done);
      },
    });
    renderWithProviders(<AdminProjectsPage />);
    const table = await screen.findByRole('table', { name: 'All projects' });
    expect(within(table).getByText('marco@example.com')).toBeInTheDocument();
    expect(within(table).getByText('Turned off')).toBeInTheDocument();
    expect(await screen.findByText('No transfers yet.')).toBeInTheDocument();

    await userEvent.click(within(table).getByRole('button', { name: 'Transfer Billing' }));
    // The current owner and turned-off accounts can't receive it.
    await userEvent.click(await screen.findByRole('textbox', { name: 'New owner' }));
    expect(screen.queryByRole('option', { name: /Marco/ })).not.toBeInTheDocument();
    await pickNewOwner('Anna (anna@example.com)');

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ to_user_id: 'u3' });
    const history = await screen.findByRole('table', { name: 'Transfer history' });
    expect(within(history).getByText(done.summary)).toBeInTheDocument();
  });
});

describe('AdminUsersPage transfers', () => {
  it('transfers everything a user owns', async () => {
    const fetchMock = mockFetch({
      'GET /api/v1/admin/users?page=1&page_size=50': () => page([testUser, marco, anna]),
      'GET /api/v1/admin/users?page=1&page_size=100': () => page([testUser, marco, anna]),
      'POST /api/v1/admin/users/u2/transfer': () => jsonResponse({ ...done, project_id: null }),
    });
    renderWithProviders(<AdminUsersPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Transfer everything marco@example.com owns' }));
    expect(await screen.findByText(/Every project and connection of marco@example.com/)).toBeInTheDocument();
    await pickNewOwner('Alice (alice@example.com)');

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(post?.[0]).toBe('/api/v1/admin/users/u2/transfer');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ to_user_id: 'u1' });
  });
});
