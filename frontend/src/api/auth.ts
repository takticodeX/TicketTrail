import { apiRequest, setAccessToken } from './client';
import type { AuthConfig, LoginPayload, RegisterPayload, TokenResponse, User } from './types';

export function fetchAuthConfig(): Promise<AuthConfig> {
  return apiRequest<AuthConfig>('/auth/config', { auth: false });
}

export async function login(payload: LoginPayload): Promise<void> {
  const tokens = await apiRequest<TokenResponse>('/auth/login', {
    method: 'POST',
    body: payload,
    auth: false,
  });
  setAccessToken(tokens.access_token);
}

export function register(payload: RegisterPayload): Promise<User> {
  return apiRequest<User>('/auth/register', { method: 'POST', body: payload, auth: false });
}

export async function logout(): Promise<void> {
  try {
    await apiRequest<void>('/auth/logout', { method: 'POST', auth: false });
  } finally {
    setAccessToken(null);
  }
}

export function fetchMe(): Promise<User> {
  return apiRequest<User>('/me');
}
