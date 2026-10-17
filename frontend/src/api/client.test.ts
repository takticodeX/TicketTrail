import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorResponse, jsonResponse, mockFetch } from '../test/utils';
import {
  ApiError,
  apiRequest,
  getAccessToken,
  onSessionExpired,
  refreshAccessToken,
  setAccessToken,
} from './client';

const token = (value: string) => ({ access_token: value, token_type: 'bearer', expires_in: 900 });
const authHeader = (init: RequestInit | undefined) =>
  (init?.headers as Record<string, string> | undefined)?.Authorization;

beforeEach(() => {
  setAccessToken(null);
  onSessionExpired(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiRequest', () => {
  it('sends the access token and parses JSON', async () => {
    setAccessToken('abc');
    const fetchMock = mockFetch({ 'GET /api/v1/me': [jsonResponse({ id: '1' })] });

    await expect(apiRequest('/me')).resolves.toEqual({ id: '1' });
    expect(authHeader(fetchMock.mock.calls[0]?.[1])).toBe('Bearer abc');
  });

  it('does not send a token when auth is off', async () => {
    setAccessToken('abc');
    const fetchMock = mockFetch({ 'POST /api/v1/auth/login': [jsonResponse(token('t'))] });

    await apiRequest('/auth/login', { method: 'POST', body: {}, auth: false });
    expect(authHeader(fetchMock.mock.calls[0]?.[1])).toBeUndefined();
  });

  it('refreshes silently on 401 and retries with the new token', async () => {
    setAccessToken('expired');
    const fetchMock = mockFetch({
      'GET /api/v1/me': [errorResponse(401, 'token_expired'), jsonResponse({ id: '1' })],
      'POST /api/v1/auth/refresh': [jsonResponse(token('fresh'))],
    });

    await expect(apiRequest('/me')).resolves.toEqual({ id: '1' });
    expect(getAccessToken()).toBe('fresh');
    expect(authHeader(fetchMock.mock.calls[2]?.[1])).toBe('Bearer fresh');
  });

  it('shares one refresh between concurrent 401s', async () => {
    setAccessToken('expired');
    const fetchMock = mockFetch({
      'GET /api/v1/me': [
        errorResponse(401, 'token_expired'),
        errorResponse(401, 'token_expired'),
        jsonResponse({ id: '1' }),
        jsonResponse({ id: '1' }),
      ],
      'POST /api/v1/auth/refresh': [jsonResponse(token('fresh'))],
    });

    await Promise.all([apiRequest('/me'), apiRequest('/me')]);
    const refreshCalls = fetchMock.mock.calls.filter(([url]) => url === '/api/v1/auth/refresh');
    expect(refreshCalls).toHaveLength(1);
  });

  it('reports an expired session when the refresh fails', async () => {
    setAccessToken('expired');
    const expired = vi.fn();
    onSessionExpired(expired);
    mockFetch({
      'GET /api/v1/me': [errorResponse(401, 'token_expired', 'The access token has expired.')],
      'POST /api/v1/auth/refresh': [errorResponse(401, 'invalid_refresh_token')],
    });

    const error = await apiRequest('/me').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect(expired).toHaveBeenCalledOnce();
    expect(getAccessToken()).toBeNull();
  });

  it('turns the API error shape into an ApiError', async () => {
    mockFetch({
      'POST /api/v1/auth/register': [errorResponse(409, 'email_taken', 'Already registered.')],
    });

    const error = (await apiRequest('/auth/register', { method: 'POST', body: {}, auth: false }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.code).toBe('email_taken');
    expect(error.message).toBe('Already registered.');
    expect(error.status).toBe(409);
  });

  it('handles non-JSON error pages', async () => {
    mockFetch({ 'GET /api/v1/me': [new Response('<html>Bad gateway</html>', { status: 502 })] });

    const error = (await apiRequest('/me', { auth: false }).catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(error.code).toBe('http_error');
  });

  it('returns undefined for 204 responses', async () => {
    mockFetch({ 'POST /api/v1/auth/logout': [new Response(null, { status: 204 })] });
    await expect(apiRequest('/auth/logout', { method: 'POST', auth: false })).resolves.toBeUndefined();
  });
});

describe('refreshAccessToken', () => {
  it('retries once when another tab refreshed first', async () => {
    const fetchMock = mockFetch({
      'POST /api/v1/auth/refresh': [
        errorResponse(401, 'refresh_token_superseded'),
        jsonResponse(token('from-retry')),
      ],
    });
    await expect(refreshAccessToken()).resolves.toBe('from-retry');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not retry an invalid refresh token', async () => {
    const fetchMock = mockFetch({
      'POST /api/v1/auth/refresh': [errorResponse(401, 'invalid_refresh_token')],
    });
    await expect(refreshAccessToken()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('gives up after one retry', async () => {
    const fetchMock = mockFetch({
      'POST /api/v1/auth/refresh': [
        errorResponse(401, 'refresh_token_superseded'),
        errorResponse(401, 'refresh_token_superseded'),
      ],
    });
    await expect(refreshAccessToken()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('returns null when the network fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(refreshAccessToken()).resolves.toBeNull();
  });
});
