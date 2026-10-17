import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getAccessToken, setAccessToken } from '../api/client';
import type { User } from '../api/types';
import { errorResponse, jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { AuthProvider, useAuth } from './useAuth';

const alice: User = {
  id: 'u1',
  email: 'alice@example.com',
  display_name: 'Alice',
  timezone: 'UTC',
  role: 'admin',
  is_active: true,
  created_at: '2026-10-15T10:00:00Z',
};
const tokens = { access_token: 'tok', token_type: 'bearer', expires_in: 900 };

function Probe() {
  const { status, user, logout } = useAuth();
  return (
    <div>
      <span>status:{status}</span>
      <span>user:{user?.display_name ?? '-'}</span>
      <button onClick={() => void logout()}>logout</button>
    </div>
  );
}

beforeEach(() => setAccessToken(null));
afterEach(() => vi.unstubAllGlobals());

describe('AuthProvider', () => {
  it('restores the session from the refresh cookie on load', async () => {
    mockFetch({
      'POST /api/v1/auth/refresh': [jsonResponse(tokens)],
      'GET /api/v1/me': [jsonResponse(alice)],
    });
    renderWithProviders(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    expect(screen.getByText('status:loading')).toBeInTheDocument();
    expect(await screen.findByText('status:authenticated')).toBeInTheDocument();
    expect(screen.getByText('user:Alice')).toBeInTheDocument();
  });

  it('is anonymous when there is no valid refresh cookie', async () => {
    mockFetch({ 'POST /api/v1/auth/refresh': [errorResponse(401, 'invalid_refresh_token')] });
    renderWithProviders(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    expect(await screen.findByText('status:anonymous')).toBeInTheDocument();
  });

  it('logs out on the server and forgets the access token', async () => {
    const fetchMock = mockFetch({
      'POST /api/v1/auth/refresh': [jsonResponse(tokens)],
      'GET /api/v1/me': [jsonResponse(alice)],
      'POST /api/v1/auth/logout': [new Response(null, { status: 204 })],
    });
    renderWithProviders(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await screen.findByText('status:authenticated');

    await userEvent.click(screen.getByRole('button', { name: 'logout' }));
    await waitFor(() => expect(screen.getByText('status:anonymous')).toBeInTheDocument());
    expect(getAccessToken()).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/auth/logout')).toBe(true);
  });
});
