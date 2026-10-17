import { zodResolver } from '@hookform/resolvers/zod';
import {
  Alert,
  Anchor,
  Button,
  Center,
  Loader,
  PasswordInput,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, Navigate, useNavigate } from 'react-router-dom';

import { ApiError } from '../api/client';
import { AuthCard } from '../components/AuthCard';
import { useAuth } from '../hooks/useAuth';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { PASSWORD_MIN_LENGTH, registerSchema, type RegisterValues } from '../schemas/auth';

export function RegisterPage() {
  const { register: registerAccount } = useAuth();
  const { data: config, isPending } = useAuthConfig();
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: '', displayName: '', password: '', confirmPassword: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await registerAccount({
        email: values.email,
        password: values.password,
        display_name: values.displayName || undefined,
      });
      navigate('/', { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'email_taken') {
        setError('email', { message: error.message });
      } else {
        setFormError(error instanceof ApiError ? error.message : 'Could not reach the server. Try again.');
      }
    }
  });

  if (isPending) {
    return (
      <Center h="100vh">
        <Loader aria-label="Loading" />
      </Center>
    );
  }
  if (config && !config.allow_registration) return <Navigate to="/login" replace />;

  return (
    <AuthCard title="Create an account" subtitle="The first account becomes the administrator.">
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
          <TextInput
            label="Display name"
            description="Optional. Defaults to the part of your email before the @."
            autoComplete="name"
            error={errors.displayName?.message}
            {...register('displayName')}
          />
          <PasswordInput
            label="Password"
            description={`At least ${PASSWORD_MIN_LENGTH} characters.`}
            autoComplete="new-password"
            error={errors.password?.message}
            {...register('password')}
          />
          <PasswordInput
            label="Confirm password"
            autoComplete="new-password"
            error={errors.confirmPassword?.message}
            {...register('confirmPassword')}
          />
          <Button type="submit" loading={isSubmitting} fullWidth>
            Create account
          </Button>
          <Text size="sm" ta="center">
            Already have an account?{' '}
            <Anchor component={Link} to="/login">
              Log in
            </Anchor>
          </Text>
        </Stack>
      </form>
    </AuthCard>
  );
}
