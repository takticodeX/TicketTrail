import type { ErrorBody, TokenResponse } from './types';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// The access token lives only in memory. The refresh token is an httpOnly cookie
// the browser sends to /api/v1/auth/* on its own; JavaScript never sees it.
let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;
let sessionExpiredHandler: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Called when a refresh fails mid-session, so the app can send the user to login. */
export function onSessionExpired(handler: (() => void) | null): void {
  sessionExpiredHandler = handler;
}

function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON (for example an Nginx error page).
  }
  if (isErrorBody(body)) {
    return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  }
  return new ApiError(response.status, 'http_error', `Request failed (${response.status}).`);
}

/** Pause before retrying a refresh that lost the race to another tab. */
export const SUPERSEDED_RETRY_DELAY_MS = 250;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function postRefresh(): Promise<Response> {
  return fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  });
}

/**
 * Trade the refresh cookie for a new access token. Concurrent callers in this tab
 * share one request: the server rotates the cookie on every use. If another tab
 * rotated it first, the server answers `refresh_token_superseded`; by then the
 * browser holds that tab's new cookie, so one retry succeeds.
 */
export function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= (async () => {
    try {
      let response = await postRefresh();
      if (response.status === 401) {
        const error = await toApiError(response);
        if (error.code === 'refresh_token_superseded') {
          await sleep(SUPERSEDED_RETRY_DELAY_MS);
          response = await postRefresh();
        }
      }
      if (!response.ok) {
        setAccessToken(null);
        return null;
      }
      const body = (await response.json()) as TokenResponse;
      setAccessToken(body.access_token);
      return body.access_token;
    } catch {
      setAccessToken(null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Send the access token and refresh it once on a 401. Off for login and register. */
  auth?: boolean;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, signal } = options;

  const send = (token: string | null): Promise<Response> => {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth && token) headers.Authorization = `Bearer ${token}`;
    return fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    });
  };

  let response = await send(accessToken);
  if (response.status === 401 && auth) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      response = await send(newToken);
    } else {
      sessionExpiredHandler?.();
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
