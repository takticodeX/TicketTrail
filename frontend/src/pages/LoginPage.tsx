import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Anchor, Button, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { ApiError } from '../api/client';
import { AuthCard } from '../components/AuthCard';
import { useAuth } from '../hooks/useAuth';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { loginSchema, type LoginValues } from '../schemas/auth';

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Could not reach the server. Try again.';
}

export function LoginPage() {
  const { login } = useAuth();
  const { data: config } = useAuthConfig();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== '/login' ? from : '/', { replace: true });
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  return (
    <AuthCard title="Log in">
      <form onSubmit={onSubmit} noValidate>
        <Stack>
          {formError && (
            <Alert color="red" variant="light" role="alert">
              {formError}
            </Alert>
          )}
          <TextInput
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus
            error={errors.email?.message}
            {...register('email')}
          />
          <PasswordInput
            label="Password"
            autoComplete="current-password"
            error={errors.password?.message}
            {...register('password')}
          />
          <Button type="submit" loading={isSubmitting} fullWidth>
            Log in
          </Button>
          {config?.allow_registration && (
            <Text size="sm" ta="center">
              No account yet?{' '}
              <Anchor component={Link} to="/register">
                Create one
              </Anchor>
            </Text>
          )}
        </Stack>
      </form>
    </AuthCard>
  );
}
