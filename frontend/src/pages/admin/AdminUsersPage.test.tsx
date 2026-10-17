import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AdminUser } from '../../api/admin';
import { useAuth } from '../../hooks/useAuth';
import { authValue, jsonResponse, mockFetch, renderWithProviders, testUser } from '../../test/utils';
import { AdminUsersPage } from './AdminUsersPage';

vi.mock('../../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));
afterEach(() => vi.unstubAllGlobals());

const admin: AdminUser = { ...testUser, projects: 2 };
const bob: AdminUser = {
  ...testUser,
  id: 'u2',
  email: 'bob@example.com',
  display_name: 'Bob',
  role: 'user',
  projects: 0,
};
const users = (items: AdminUser[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 50 });

describe('AdminUsersPage', () => {
  it('lists users, without a button for yourself', async () => {
    mockFetch({ 'GET /api/v1/admin/users?page=1&page_size=50': () => users([admin, bob]) });
    renderWithProviders(<AdminUsersPage />);
    const table = await screen.findByRole('table', { name: 'Users' });
    expect(within(table).getByText('bob@example.com')).toBeInTheDocument();
    expect(within(table).getAllByRole('button')).toHaveLength(1);
    expect(within(table).getByRole('button', { name: 'Turn off bob@example.com' })).toBeInTheDocument();
  });

  it('turns an account off after confirming', async () => {
    let current = bob;
    const fetchMock = mockFetch({
      'GET /api/v1/admin/users?page=1&page_size=50': () => users([admin, current]),
      'PATCH /api/v1/admin/users/u2': (_url, init) => {
        current = { ...bob, is_active: JSON.parse(String(init?.body)).is_active };
        return jsonResponse(current);
      },
    });
    renderWithProviders(<AdminUsersPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Turn off bob@example.com' }));
    expect(await screen.findByText(/signed out everywhere/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }));

    expect(await screen.findByRole('button', { name: 'Turn on bob@example.com' })).toBeInTheDocument();
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ is_active: false });
  });
});
