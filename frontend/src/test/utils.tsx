import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

import { ROUTER_FUTURE } from '../App';
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
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
  return render(ui, { wrapper: Wrapper });
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
