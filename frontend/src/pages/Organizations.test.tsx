import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AdminOrganization } from '../api/admin';
import type { Organization, OrganizationMember, Project } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { OWN_PROJECT, authValue, jsonResponse, mockFetch, renderWithProviders } from '../test/utils';
import { AdminOrganizationsPage } from './admin/AdminOrganizationsPage';
import { DashboardPage } from './DashboardPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import { OrganizationPage } from './settings/OrganizationPage';
import { OrganizationsPage } from './settings/OrganizationsPage';
import { ProjectWizardPage } from './settings/ProjectWizardPage';

vi.mock('../hooks/useAuth', () => ({ useAuth: vi.fn() }));
beforeEach(() => vi.mocked(useAuth).mockReturnValue(authValue()));
afterEach(() => vi.unstubAllGlobals());

const acme: Organization = {
  id: 'o1',
  name: 'Acme',
  timezone: 'Asia/Tokyo',
  role: 'admin',
  members: 2,
  projects: 1,
  created_at: '',
};
const alice = { id: 'u1', display_name: 'Alice', email: 'alice@example.com' };
const ben = { id: 'u2', display_name: 'Ben', email: 'ben@example.com' };
const members: OrganizationMember[] = [
  { user: alice, role: 'admin', created_at: '' },
  { user: ben, role: 'member', created_at: '' },
];
const project: Project = {
  id: 'p1',
  name: 'Shop',
  git_connection_id: 'g1',
  azure_connection_id: 'a1',
  branches: [],
  ticket_pattern: 'AB#(\\d+)',
  comment_template: '{subject} tt:{sha}',
  start_from: null,
  include_merge_commits: false,
  schedule_cron: null,
  schedule_enabled: false,
  dry_run_default: false,
  created_at: '',
  updated_at: '',
  last_run: null,
  next_run_at: null,
  comments_posted: 0,
  ...OWN_PROJECT,
  owner: null,
  organization: { id: 'o1', name: 'Acme' },
};
const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, page: 1, page_size: 100 });
const body = (init: RequestInit | undefined) => JSON.parse(String(init?.body)) as unknown;

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/settings/organizations" element={<OrganizationsPage />} />
      <Route path="/settings/organizations/:organizationId" element={<OrganizationPage />} />
      <Route path="/settings/projects/new" element={<ProjectWizardPage />} />
    </Routes>,
    { route },
  );
}

describe('OrganizationsPage', () => {
  it('lists your organizations and creates one', async () => {
    const fetchMock = mockFetch({
      'GET /api/v1/organizations': () => jsonResponse([acme]),
      'POST /api/v1/organizations': () => jsonResponse({ ...acme, id: 'o2', name: 'Beta' }, 201),
      'GET /api/v1/organizations/o2': () => jsonResponse({ ...acme, id: 'o2', name: 'Beta' }),
      'GET /api/v1/organizations/o2/members': () => jsonResponse(members),
      'GET /api/v1/git-connections?page_size=100&organization_id=o2': () => page([]),
      'GET /api/v1/azure-connections?page_size=100&organization_id=o2': () => page([]),
      'GET /api/v1/projects?page_size=100': () => page([]),
    });
    renderAt('/settings/organizations');
    const table = await screen.findByRole('table', { name: 'Organizations' });
    expect(within(table).getByRole('link', { name: 'Acme' })).toBeInTheDocument();
    expect(within(table).getByText('Admin')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'New organization' }));
    const dialog = await screen.findByRole('dialog', { name: 'New organization' });
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Beta');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }));

    expect(await screen.findByRole('heading', { name: 'Beta' })).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(body(post?.[1])).toEqual({ name: 'Beta' });
  });
});

describe('OrganizationPage', () => {
  const routes = (org: Organization, extra: Parameters<typeof mockFetch>[0] = {}) =>
    mockFetch({
      'GET /api/v1/organizations/o1': () => jsonResponse(org),
      'GET /api/v1/organizations/o1/members': () => jsonResponse(members),
      'GET /api/v1/git-connections?page_size=100&organization_id=o1': () =>
        page([
          { id: 'g1', name: 'Acme repo', repo_url: 'https://github.com/acme/shop', last_test_ok: true, last_test_at: '2026-10-20T10:00:00Z' },
        ]),
      'GET /api/v1/azure-connections?page_size=100&organization_id=o1': () => page([]),
      'GET /api/v1/projects?page_size=100': () => page([project]),
      ...extra,
    });

  it('lets an admin add members and manage connections', async () => {
    const fetchMock = routes(acme, {
      'POST /api/v1/organizations/o1/members': () =>
        jsonResponse({ user: { id: 'u3', display_name: 'Cy', email: 'cy@example.com' }, role: 'member' }, 201),
    });
    renderAt('/settings/organizations/o1');
    expect(await screen.findByRole('heading', { name: 'Acme' })).toBeInTheDocument();
    expect(screen.getByText('Schedules run in Asia/Tokyo.')).toBeInTheDocument();
    const list = await screen.findByRole('table', { name: 'Members' });
    expect(within(list).getByText('ben@example.com')).toBeInTheDocument();
    expect(await screen.findByText('Acme repo')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Shop' })).toBeInTheDocument();

    await userEvent.type(screen.getByRole('textbox', { name: 'Email' }), 'cy@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(body(post?.[1])).toEqual({ email: 'cy@example.com', role: 'member' });

    await userEvent.click(screen.getByRole('button', { name: 'Add Git connection' }));
    expect(await screen.findByRole('dialog', { name: 'New Git connection for Acme' })).toBeInTheDocument();
  });

  it('shows a member the organization without the admin tools', async () => {
    vi.mocked(useAuth).mockReturnValue(authValue({ user: { ...authValue().user!, id: 'u2', email: ben.email } }));
    routes({ ...acme, role: 'member' });
    renderAt('/settings/organizations/o1');
    expect(await screen.findByText('Member')).toBeInTheDocument();
    expect(await screen.findByText('Acme repo')).toBeInTheDocument();
    for (const name of ['Add member', 'Add Git connection', 'Delete organization', 'Edit']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Leave the organization' })).toBeInTheDocument();
  });
});

describe('organization projects', () => {
  it('groups organization projects on the dashboard', async () => {
    mockFetch({
      'GET /api/v1/projects?page_size=100': () =>
        page([
          { ...project, id: 'p0', name: 'Mine', owner: alice, organization: null },
          { ...project, role: 'viewer' },
        ]),
    });
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Acme' })).toBeInTheDocument();
    const card = screen.getByLabelText('Shop');
    expect(within(card).getByText('Viewer')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
  });

  it("offers an organization's admin to move the project to a member", async () => {
    const fetchMock = mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse(project),
      'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page([]),
      'GET /api/v1/organizations': () => jsonResponse([acme]),
      'GET /api/v1/organizations/o1/members': () => jsonResponse(members),
      'POST /api/v1/projects/p1/move': () => jsonResponse({ project_id: 'p1', summary: 'Moved' }),
      'GET /api/v1/projects?page_size=100': () => page([]),
    });
    renderAt('/projects/p1');
    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Leave' })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'Move to a member' }));
    const dialog = await screen.findByRole('dialog', { name: 'Move to a member' });
    await userEvent.click(within(dialog).getByRole('textbox', { name: 'Member' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Ben (ben@example.com)' }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }));

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(body(post?.[1])).toEqual({ to_user_id: 'u2' });
  });

  it('moves a personal project into an organization', async () => {
    const personal = { ...project, owner: alice, organization: null };
    const fetchMock = mockFetch({
      'GET /api/v1/projects/p1': () => jsonResponse(personal),
      'GET /api/v1/projects/p1/runs?page=1&page_size=20': () => page([]),
      'GET /api/v1/organizations': () => jsonResponse([acme]),
      'POST /api/v1/projects/p1/move': () => jsonResponse({ project_id: 'p1', summary: 'Moved' }),
    });
    renderAt('/projects/p1');
    await userEvent.click(await screen.findByRole('button', { name: 'Move to an organization' }));
    const dialog = await screen.findByRole('dialog', { name: 'Move to an organization' });
    await userEvent.click(within(dialog).getByRole('textbox', { name: 'Organization' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Acme' }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(body(post?.[1])).toEqual({ organization_id: 'o1' });
  });

  it('creates a project for the organization picked in the wizard', async () => {
    mockFetch({
      'GET /api/v1/organizations': () => jsonResponse([acme]),
      'GET /api/v1/git-connections?page_size=100&organization_id=o1': () =>
        page([{ id: 'g9', name: 'Acme repo', repo_url: 'https://github.com/acme/shop', commit_url_pattern: '' }]),
      'GET /api/v1/azure-connections?page_size=100&organization_id=o1': () => page([]),
    });
    renderAt('/settings/projects/new?organization=o1');
    expect(await screen.findByRole('textbox', { name: 'Owner' })).toHaveValue('Acme');
    await userEvent.click(screen.getByRole('textbox', { name: 'Git connection' }));
    expect(await screen.findByRole('option', { name: 'Acme repo' })).toBeInTheDocument();
  });
});

describe('AdminOrganizationsPage', () => {
  it('names an admin for an organization that has none', async () => {
    const orphan: AdminOrganization = {
      id: 'o1',
      name: 'Acme',
      timezone: 'UTC',
      members: 1,
      admins: [],
      people: [{ user: ben, role: 'member', created_at: '' }],
      projects: 1,
      connections: 2,
      created_at: '',
    };
    const fetchMock = mockFetch({
      'GET /api/v1/admin/organizations?page=1&page_size=50': () => page([orphan]),
      'POST /api/v1/admin/organizations/o1/admins': () =>
        jsonResponse({ ...orphan, admins: [ben], people: [{ user: ben, role: 'admin', created_at: '' }] }),
    });
    renderWithProviders(<AdminOrganizationsPage />);
    expect(await screen.findByText('No admin')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Make an admin of Acme' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('textbox', { name: 'Member' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Ben (ben@example.com)' }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Make admin' }));
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(body(post?.[1])).toEqual({ user_id: 'u2' });
  });
});
