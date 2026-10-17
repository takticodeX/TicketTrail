import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AzureConnection, GitConnection, Project } from '../../api/types';
import { useAuth } from '../../hooks/useAuth';
import { authValue, jsonResponse, mockFetch, renderWithProviders } from '../../test/utils';
import { ProjectWizardPage } from './ProjectWizardPage';

vi.mock('../../hooks/useAuth', () => ({ useAuth: vi.fn() }));

const git = {
  id: 'g1',
  name: 'App repo',
  repo_url: 'https://github.com/acme/app.git',
  commit_url_pattern: 'https://github.com/acme/app/commit/{sha}',
} as GitConnection;
const azure = { id: 'a1', name: 'Board', azure_project: 'proj' } as AzureConnection;
const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 100 });

beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));
afterEach(() => vi.unstubAllGlobals());

function renderWizard(route = '/settings/projects/new') {
  return renderWithProviders(
    <Routes>
      <Route path="/settings/projects/new" element={<ProjectWizardPage />} />
      <Route path="/settings/projects/:projectId" element={<ProjectWizardPage />} />
      <Route path="/settings/projects" element={<p>projects list</p>} />
    </Routes>,
    { route },
  );
}

async function pick(label: string, option: string) {
  await userEvent.click(screen.getByRole('textbox', { name: label }));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

describe('ProjectWizardPage', () => {
  it('walks through the steps and creates a project', async () => {
    const fetchMock = mockFetch({
      'GET /api/v1/git-connections?page_size=100': () => page([git]),
      'GET /api/v1/azure-connections?page_size=100': () => page([azure]),
      'POST /api/v1/git-connections/g1/test': () =>
        jsonResponse({ ok: true, branches: ['develop', 'main'], default_branch: 'main', error: null }),
      'POST /api/v1/projects/test-pattern': () =>
        jsonResponse({ pattern: 'AB#(\\d+)', results: [{ ids: [123], error: null }, { ids: [45, 46], error: null }, { ids: [], error: null }] }),
      'POST /api/v1/projects': (_url, init) => jsonResponse({ id: 'p1', ...JSON.parse(String(init?.body)) }, 201),
    });
    renderWizard();

    // Repository
    await userEvent.type(screen.getByLabelText('Project name'), 'Web app');
    await pick('Git connection', 'App repo');
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Branches: load them from the repository, then pick one.
    await userEvent.click(await screen.findByRole('button', { name: 'Load branches from the repository' }));
    expect(await screen.findByText('Connection works')).toBeInTheDocument();
    expect(screen.getByText(/default branch \(main\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Board
    await pick('Azure connection', 'Board (proj)');
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Ticket pattern, with the live tester
    expect(await screen.findByText('#123')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Comment, with the preview
    expect(await screen.findByLabelText('Rendered preview')).toHaveTextContent('Fix login redirect AB#123');
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Start point
    await userEvent.click(screen.getByRole('radio', { name: 'A date' }));
    await userEvent.type(screen.getByLabelText('Start date'), '2026-01-31');
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Schedule
    await userEvent.click(screen.getByRole('switch', { name: /Sync on a schedule/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Create project' }));

    expect(await screen.findByText('projects list')).toBeInTheDocument();
    const create = fetchMock.mock.calls.find(([url, init]) => url === '/api/v1/projects' && init?.method === 'POST');
    expect(JSON.parse(String(create?.[1]?.body))).toMatchObject({
      name: 'Web app',
      git_connection_id: 'g1',
      azure_connection_id: 'a1',
      branches: [],
      ticket_pattern: 'AB#(\\d+)',
      start_from: '2026-01-31',
      schedule_cron: '0 * * * *',
      schedule_enabled: true,
    });
  });

  it('does not advance past a step with errors', async () => {
    mockFetch({
      'GET /api/v1/git-connections?page_size=100': () => page([git]),
      'GET /api/v1/azure-connections?page_size=100': () => page([azure]),
    });
    renderWizard();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Name is required')).toBeInTheDocument();
    expect(screen.getByText('Pick a Git connection')).toBeInTheDocument();
  });

  it('edits an existing project and shows server errors on their step', async () => {
    const project: Project = {
      id: 'p1',
      name: 'Web app',
      git_connection_id: 'g1',
      azure_connection_id: 'a1',
      branches: ['main'],
      ticket_pattern: 'AB#(\\d+)',
      comment_template: '{subject} tt:{sha}',
      start_from: null,
      include_merge_commits: false,
      schedule_cron: null,
      schedule_enabled: false,
      dry_run_default: false,
      created_at: '',
      updated_at: '',
    };
    mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse(project),
      'GET /api/v1/git-connections?page_size=100': () => page([git]),
      'GET /api/v1/azure-connections?page_size=100': () => page([azure]),
      'PATCH /api/v1/projects/p1': () =>
        jsonResponse(
          {
            error: {
              code: 'validation_error',
              message: 'The request is invalid.',
              details: { errors: [{ loc: ['body', 'name'], msg: 'Value error, name problem', type: 'value_error' }] },
            },
          },
          422,
        ),
    });
    renderWizard('/settings/projects/p1');

    expect(await screen.findByRole('heading', { name: 'Edit Web app' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByText('name problem')).toBeInTheDocument());
    expect(screen.getByLabelText('Project name')).toHaveValue('Web app');
  });
});
