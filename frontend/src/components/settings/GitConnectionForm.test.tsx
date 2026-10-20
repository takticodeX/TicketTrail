import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { GitConnection } from '../../api/types';
import { jsonResponse, mockFetch, renderWithProviders } from '../../test/utils';
import { GitConnectionForm } from './GitConnectionForm';

const saved: GitConnection = {
  id: 'g1',
  name: 'App repo',
  organization_id: null,
  repo_url: 'https://github.com/acme/app.git',
  auth_type: 'token',
  username: 'x-access-token',
  has_secret: true,
  commit_url_template: null,
  commit_url_pattern: 'https://github.com/acme/app/commit/{sha}',
  host: 'github',
  last_test_at: null,
  last_test_ok: null,
  created_at: '',
  updated_at: '',
};

afterEach(() => vi.unstubAllGlobals());

function bodyOf(init: RequestInit | undefined): unknown {
  return JSON.parse(String(init?.body));
}

describe('GitConnectionForm', () => {
  it('suggests the username for the detected host', async () => {
    renderWithProviders(<GitConnectionForm connection={null} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('Repository URL'), 'https://gitlab.com/acme/app.git');
    expect(screen.getByLabelText('Username')).toHaveValue('oauth2');
    expect(screen.getByText(/read_repository/)).toBeInTheDocument();
  });

  it('keeps a username the user typed', async () => {
    renderWithProviders(<GitConnectionForm connection={null} onSaved={vi.fn()} onClose={vi.fn()} />);
    const username = screen.getByLabelText('Username');
    await userEvent.clear(username);
    await userEvent.type(username, 'me');
    await userEvent.type(screen.getByLabelText('Repository URL'), 'https://github.com/acme/app.git');
    expect(username).toHaveValue('me');
  });

  it('creates a connection with the secret', async () => {
    const fetchMock = mockFetch({ 'POST /api/v1/git-connections': [jsonResponse(saved, 201)] });
    const onSaved = vi.fn();
    renderWithProviders(<GitConnectionForm connection={null} onSaved={onSaved} onClose={vi.fn()} />);

    await userEvent.type(screen.getByLabelText('Name'), 'App repo');
    await userEvent.type(screen.getByLabelText('Repository URL'), 'https://github.com/acme/app.git');
    await userEvent.type(screen.getByLabelText('Access token'), 'ghp_secret');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(bodyOf(fetchMock.mock.calls[0]?.[1])).toEqual({
      name: 'App repo',
      repo_url: 'https://github.com/acme/app.git',
      auth_type: 'token',
      username: 'x-access-token',
      secret: 'ghp_secret',
      commit_url_template: null,
    });
  });

  it('shows a saved secret and does not resend it', async () => {
    const fetchMock = mockFetch({
      'PATCH /api/v1/git-connections/g1': [jsonResponse({ ...saved, name: 'Renamed' })],
    });
    renderWithProviders(<GitConnectionForm connection={saved} onSaved={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByLabelText('Access token')).toHaveAttribute('placeholder', '••••••• (saved)');
    const name = screen.getByLabelText('Name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Renamed');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(bodyOf(fetchMock.mock.calls[0]?.[1])).not.toHaveProperty('secret');
  });

  it('shows the test result after "Save and test" on a new connection', async () => {
    // Found by the end-to-end test: the result used to vanish when the form switched to edit mode.
    mockFetch({
      'POST /api/v1/git-connections': [jsonResponse(saved, 201)],
      'POST /api/v1/git-connections/g1/test': [
        jsonResponse({ ok: true, branches: ['main'], default_branch: 'main', error: null }),
      ],
      'GET /api/v1/git-connections?page_size=100': () =>
        jsonResponse({ items: [saved], total: 1, page: 1, page_size: 100 }),
    });
    function Harness() {
      const [connection, setConnection] = useState<GitConnection | null>(null);
      return <GitConnectionForm connection={connection} onSaved={setConnection} onClose={vi.fn()} />;
    }
    renderWithProviders(<Harness />);
    await userEvent.type(screen.getByLabelText('Name'), 'App repo');
    await userEvent.type(screen.getByLabelText('Repository URL'), 'https://github.com/acme/app.git');
    await userEvent.type(screen.getByLabelText('Access token'), 'ghp_secret');
    await userEvent.click(screen.getByRole('button', { name: 'Save and test' }));
    expect(await screen.findByText('Connection works')).toBeInTheDocument();
  });

  it('rejects http URLs before saving', async () => {
    const fetchMock = mockFetch({});
    renderWithProviders(<GitConnectionForm connection={null} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('Name'), 'x');
    await userEvent.type(screen.getByLabelText('Repository URL'), 'http://github.com/acme/app');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Must start with https://')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('tests a saved connection and lists the branches', async () => {
    mockFetch({
      'POST /api/v1/git-connections/g1/test': [
        jsonResponse({ ok: true, branches: ['dev', 'main'], default_branch: 'main', error: null }),
      ],
      'GET /api/v1/git-connections?page_size=100': () =>
        jsonResponse({ items: [saved], total: 1, page: 1, page_size: 100 }),
    });
    renderWithProviders(<GitConnectionForm connection={saved} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    expect(await screen.findByText('Connection works')).toBeInTheDocument();
    expect(screen.getByText(/Found 2 branches/)).toBeInTheDocument();
  });

  it('shows why a test failed', async () => {
    mockFetch({
      'POST /api/v1/git-connections/g1/test': [
        jsonResponse({ ok: false, branches: [], default_branch: null, error: 'Authentication failed.' }),
      ],
      'GET /api/v1/git-connections?page_size=100': () =>
        jsonResponse({ items: [saved], total: 1, page: 1, page_size: 100 }),
    });
    renderWithProviders(<GitConnectionForm connection={saved} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Authentication failed.');
  });
});
