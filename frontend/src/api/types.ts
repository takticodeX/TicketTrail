// Mirrors the backend's Pydantic schemas (backend/app/api/v1/schemas.py).

export type UserRole = 'user' | 'admin';

export interface User {
  id: string;
  email: string;
  display_name: string;
  timezone: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}

export interface AuthConfig {
  allow_registration: boolean;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  display_name?: string;
}

export interface ErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}
