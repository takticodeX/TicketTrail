import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

import { ROUTER_FUTURE } from '../App';
import type { Project, User } from '../api/types';
import type { AuthContextValue } from '../hooks/useAuth';
import { theme } from '../theme';

export function renderWithProviders(
  ui: ReactElement,
  { route = '/' }: { route?: string } = {},
): RenderResult {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <MantineProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]} future={ROUTER_FUTURE}>
          <ModalsProvider>{children}</ModalsProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
  return render(ui, { wrapper: Wrapper });
}

export const testUser: User = {
  id: 'u1',
  email: 'alice@example.com',
  display_name: 'Alice',
  timezone: 'Europe/Rome',
  role: 'admin',
  is_active: true,
  created_at: '2026-10-15T10:00:00Z',
};

/** The sharing fields of a project the test user owns. */
export const OWN_PROJECT: Pick<
  Project,
  | 'role'
  | 'owner'
  | 'organization'
  | 'schedule_timezone'
  | 'shares'
  | 'admin_access'
  | 'git_connection'
  | 'azure_connection'
> = {
  role: 'owner',
  owner: { id: 'u1', display_name: 'Alice', email: 'alice@example.com' },
  organization: null,
  schedule_timezone: 'Europe/Rome',
  shares: 0,
  admin_access: false,
  git_connection: null,
  azure_connection: null,
};

/** A full auth context value for tests that mock useAuth. */
export function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: 'authenticated',
    user: testUser,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    updateUser: vi.fn(),
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function errorResponse(status: number, code: string, message = code): Response {
  return jsonResponse({ error: { code, message, details: {} } }, status);
}

type Handler = (url: string, init: RequestInit | undefined) => Response | Promise<Response>;

/** Replace global fetch with a mock that routes by "METHOD /path". */
export function mockFetch(routes: Record<string, Handler | Response[]>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const key = `${init?.method ?? 'GET'} ${url}`;
    const route = routes[key];
    if (!route) throw new Error(`Unexpected request: ${key}`);
    if (Array.isArray(route)) {
      const next = route.shift();
      if (!next) throw new Error(`No more responses for: ${key}`);
      return next;
    }
    return route(url, init);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
