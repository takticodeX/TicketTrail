import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { useAuth, type AuthContextValue } from '../hooks/useAuth';
import { authValue, renderWithProviders } from '../test/utils';
import { RedirectIfAuthenticated, RequireAuth } from './RequireAuth';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));

function mockStatus(status: AuthContextValue['status']) {
  vi.mocked(useAuth).mockReturnValue(authValue({ status, user: null }));
}

function renderRoutes(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<RedirectIfAuthenticated>login page</RedirectIfAuthenticated>} />
      <Route path="/" element={<RequireAuth>secret dashboard</RequireAuth>} />
    </Routes>,
    { route },
  );
}

describe('RequireAuth', () => {
  it('shows a loader while the session is being restored', () => {
    mockStatus('loading');
    renderRoutes('/');
    expect(screen.getByLabelText('Loading')).toBeInTheDocument();
    expect(screen.queryByText('secret dashboard')).not.toBeInTheDocument();
  });

  it('redirects anonymous users to /login', () => {
    mockStatus('anonymous');
    renderRoutes('/');
    expect(screen.getByText('login page')).toBeInTheDocument();
  });

  it('renders the page for signed-in users', () => {
    mockStatus('authenticated');
    renderRoutes('/');
    expect(screen.getByText('secret dashboard')).toBeInTheDocument();
  });
});

describe('RedirectIfAuthenticated', () => {
  it('sends signed-in users from /login to the dashboard', () => {
    mockStatus('authenticated');
    renderRoutes('/login');
    expect(screen.getByText('secret dashboard')).toBeInTheDocument();
  });
});
