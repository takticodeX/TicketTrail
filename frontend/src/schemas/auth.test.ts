import { describe, expect, it } from 'vitest';

import { loginSchema, registerSchema } from './auth';

const validRegistration = {
  email: 'alice@example.com',
  displayName: '',
  password: 'long-enough-1',
  confirmPassword: 'long-enough-1',
};

describe('loginSchema', () => {
  it('accepts an email and any non-empty password', () => {
    expect(loginSchema.safeParse({ email: 'a@example.com', password: 'x' }).success).toBe(true);
  });

  it('rejects an invalid email', () => {
    expect(loginSchema.safeParse({ email: 'nope', password: 'x' }).success).toBe(false);
  });

  it('rejects an empty password', () => {
    expect(loginSchema.safeParse({ email: 'a@example.com', password: '' }).success).toBe(false);
  });
});

describe('registerSchema', () => {
  it('accepts a valid registration', () => {
    expect(registerSchema.safeParse(validRegistration).success).toBe(true);
  });

  it('requires at least 10 password characters, like the API', () => {
    const result = registerSchema.safeParse({
      ...validRegistration,
      password: '123456789',
      confirmPassword: '123456789',
    });
    expect(result.success).toBe(false);
  });

  it('requires matching passwords', () => {
    const result = registerSchema.safeParse({ ...validRegistration, confirmPassword: 'different-1' });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(['confirmPassword']);
  });

  it('trims the email', () => {
    const result = registerSchema.parse({ ...validRegistration, email: '  alice@example.com ' });
    expect(result.email).toBe('alice@example.com');
  });
});
