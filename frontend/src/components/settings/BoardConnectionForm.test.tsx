import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BoardConnection } from '../../api/types';
import { jsonResponse, mockFetch, renderWithProviders } from '../../test/utils';
import { BoardConnectionForm } from './BoardConnectionForm';

const saved: BoardConnection = {
  id: 'b1',
  name: 'Acme board',
  organization_id: null,
  kind: 'azure',
  url: 'https://dev.azure.com/acme',
  scope: 'Web',
  has_secret: true,
  last_test_at: null,
  last_test_ok: null,
  created_at: '',
  updated_at: '',
};

afterEach(() => vi.unstubAllGlobals());

function bodyOf(init: RequestInit | undefined): unknown {
  return JSON.parse(String(init?.body));
}

describe('BoardConnectionForm', () => {
  it('creates an Azure DevOps connection and tests it', async () => {
    const fetchMock = mockFetch({
      'POST /api/v1/board-connections': () => jsonResponse(saved, 201),
      'POST /api/v1/board-connections/b1/test': () => jsonResponse({ ok: true, scope_name: 'Web', error: null }),
    });
    renderWithProviders(<BoardConnectionForm connection={null} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('Name'), 'Acme board');
    await userEvent.type(screen.getByLabelText('Organization URL'), 'https://dev.azure.com/acme');
    await userEvent.type(screen.getByLabelText('Project'), 'Web');
    await userEvent.type(screen.getByLabelText('Personal access token'), 'the-pat');
    await userEvent.click(screen.getByRole('button', { name: 'Save and test' }));

    expect(await screen.findByText('Web', { selector: 'strong' })).toBeInTheDocument();
    expect(bodyOf(fetchMock.mock.calls[0]?.[1])).toEqual({
      name: 'Acme board',
      kind: 'azure',
      url: 'https://dev.azure.com/acme',
      scope: 'Web',
      secret: 'the-pat',
    });
  });

  it('keeps the saved token when the field is left empty', async () => {
    const fetchMock = mockFetch({
      'PATCH /api/v1/board-connections/b1': () => jsonResponse({ ...saved, scope: 'Mobile' }),
    });
    renderWithProviders(<BoardConnectionForm connection={saved} onSaved={vi.fn()} onClose={vi.fn()} />);
    const scope = screen.getByLabelText('Project');
    await userEvent.clear(scope);
    await userEvent.type(scope, 'Mobile');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(bodyOf(fetchMock.mock.calls[0]?.[1])).toEqual({ name: 'Acme board', url: 'https://dev.azure.com/acme', scope: 'Mobile' });
  });
});
