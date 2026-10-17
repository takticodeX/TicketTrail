import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { authValue, jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { LoginPage } from './LoginPage';
import { RegisterPage } from './RegisterPage';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));

const login = vi.fn();
const registerAccount = vi.fn();

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue(
    authValue({ status: 'anonymous', user: null, login, register: registerAccount }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderAuthPages(route: string, allowRegistration = true) {
  mockFetch({
    'GET /api/v1/auth/config': () => jsonResponse({ allow_registration: allowRegistration }),
  });
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/" element={<p>dashboard</p>} />
    </Routes>,
    { route },
  );
}

describe('LoginPage', () => {
  it('validates the form before calling the API', async () => {
    renderAuthPages('/login');
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByText('Email is required')).toBeInTheDocument();
    expect(screen.getByText('Password is required')).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it('logs in and goes to the dashboard', async () => {
    login.mockResolvedValue(undefined);
    renderAuthPages('/login');
    await userEvent.type(screen.getByLabelText('Email'), 'alice@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse');
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }));

    expect(await screen.findByText('dashboard')).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith({ email: 'alice@example.com', password: 'correct-horse' });
  });

  it('shows the server error for wrong credentials', async () => {
    login.mockRejectedValue(new ApiError(401, 'invalid_credentials', 'Email or password is incorrect.'));
    renderAuthPages('/login');
    await userEvent.type(screen.getByLabelText('Email'), 'alice@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  });

  it('links to registration only when it is open', async () => {
    renderAuthPages('/login', true);
    expect(await screen.findByRole('link', { name: 'Create one' })).toBeInTheDocument();
  });

  it('hides the registration link when registration is off', async () => {
    renderAuthPages('/login', false);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(screen.queryByRole('link', { name: 'Create one' })).not.toBeInTheDocument();
  });
});

describe('RegisterPage', () => {
  it('redirects to login when registration is off', async () => {
    renderAuthPages('/register', false);
    expect(await screen.findByRole('button', { name: 'Log in' })).toBeInTheDocument();
  });

  it('checks that the passwords match', async () => {
    renderAuthPages('/register');
    await userEvent.type(await screen.findByLabelText('Email'), 'bob@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'long-enough-1');
    await userEvent.type(screen.getByLabelText('Confirm password'), 'long-enough-2');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument();
    expect(registerAccount).not.toHaveBeenCalled();
  });

  it('registers and goes to the dashboard', async () => {
    registerAccount.mockResolvedValue(undefined);
    renderAuthPages('/register');
    await userEvent.type(await screen.findByLabelText('Email'), 'bob@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'long-enough-1');
    await userEvent.type(screen.getByLabelText('Confirm password'), 'long-enough-1');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByText('dashboard')).toBeInTheDocument();
    expect(registerAccount).toHaveBeenCalledWith({
      email: 'bob@example.com',
      password: 'long-enough-1',
      display_name: undefined,
    });
  });

  it('shows "email taken" next to the email field', async () => {
    registerAccount.mockRejectedValue(new ApiError(409, 'email_taken', 'An account with this email already exists.'));
    renderAuthPages('/register');
    await userEvent.type(await screen.findByLabelText('Email'), 'bob@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'long-enough-1');
    await userEvent.type(screen.getByLabelText('Confirm password'), 'long-enough-1');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByText('An account with this email already exists.')).toBeInTheDocument();
  });
});
