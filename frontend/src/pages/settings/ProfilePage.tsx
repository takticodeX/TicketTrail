import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Button, Group, Paper, PasswordInput, Select, Stack, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMemo, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';

import { ApiError } from '../../api/client';
import { applyServerErrors } from '../../api/errors';
import { updateMe } from '../../api/settings';
import { useAuth } from '../../hooks/useAuth';
import { passwordSchema, profileSchema, type PasswordValues, type ProfileValues } from '../../schemas/settings';

function timeZones(current: string): string[] {
  const zones = new Set(Intl.supportedValuesOf('timeZone'));
  zones.add('UTC');
  zones.add(current);
  return [...zones].sort();
}

function ProfileForm() {
  const { user, updateUser } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const zones = useMemo(() => timeZones(user?.timezone ?? 'UTC'), [user?.timezone]);
  const {
    register,
    control,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: { display_name: user?.display_name ?? '', timezone: user?.timezone ?? 'UTC' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const saved = await updateMe(values);
      updateUser(saved);
      reset({ display_name: saved.display_name, timezone: saved.timezone });
      notifications.show({ color: 'teal', message: 'Profile saved.' });
    } catch (error) {
      setFormError(
        applyServerErrors(error, setError, { display_name: 'display_name', timezone: 'timezone' }),
      );
    }
  });

  return (
    <Paper withBorder radius="md" p="lg" component="form" onSubmit={onSubmit} noValidate>
      <Stack>
        <Title order={4}>Profile</Title>
        {formError && (
          <Alert color="red" variant="light" role="alert">
            {formError}
          </Alert>
        )}
        <TextInput label="Email" value={user?.email ?? ''} disabled />
        <TextInput label="Display name" error={errors.display_name?.message} {...register('display_name')} />
        <Controller
          control={control}
          name="timezone"
          render={({ field }) => (
            <Select
              label="Time zone"
              description="Schedules run, and times are shown, in this time zone."
              searchable
              allowDeselect={false}
              data={zones}
              value={field.value}
              onChange={(value) => field.onChange(value ?? 'UTC')}
              error={errors.timezone?.message}
            />
          )}
        />
        <Group justify="flex-end">
          <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
            Save profile
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function PasswordForm() {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await updateMe({ current_password: values.current_password, new_password: values.new_password });
      reset();
      notifications.show({
        color: 'teal',
        message: 'Password changed. Your other sessions have been signed out.',
      });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'invalid_current_password') {
        setError('current_password', { message: error.message });
        return;
      }
      setFormError(applyServerErrors(error, setError, { new_password: 'new_password' }));
    }
  });

  return (
    <Paper withBorder radius="md" p="lg" component="form" onSubmit={onSubmit} noValidate>
      <Stack>
        <div>
          <Title order={4}>Change password</Title>
          <Text size="sm" c="dimmed">
            This signs you out on every other device.
          </Text>
        </div>
        {formError && (
          <Alert color="red" variant="light" role="alert">
            {formError}
          </Alert>
        )}
        <PasswordInput
          label="Current password"
          autoComplete="current-password"
          error={errors.current_password?.message}
          {...register('current_password')}
        />
        <PasswordInput
          label="New password"
          description="At least 10 characters."
          autoComplete="new-password"
          error={errors.new_password?.message}
          {...register('new_password')}
        />
        <PasswordInput
          label="Confirm new password"
          autoComplete="new-password"
          error={errors.confirm_password?.message}
          {...register('confirm_password')}
        />
        <Group justify="flex-end">
          <Button type="submit" loading={isSubmitting}>
            Change password
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

export function ProfilePage() {
  return (
    <Stack maw={640}>
      <Title order={2}>Profile</Title>
      <ProfileForm />
      <PasswordForm />
    </Stack>
  );
}
