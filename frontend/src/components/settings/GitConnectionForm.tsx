import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Button, Group, SegmentedControl, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useEffect, useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';

import { applyServerErrors, errorMessage } from '../../api/errors';
import type { GitConnection, GitConnectionInput, GitTestResult } from '../../api/types';
import { useSaveGitConnection, useTestGitConnection } from '../../hooks/useSettings';
import { DEFAULT_USERNAMES, HOST_LABELS, SECRET_HINTS, detectHost } from '../../lib/gitHosts';
import { gitConnectionSchema, type GitConnectionValues } from '../../schemas/settings';
import { SecretInput } from '../SecretInput';
import { GitTestResultView } from './ConnectionTestResult';

const FIELDS = {
  name: 'name',
  repo_url: 'repo_url',
  auth_type: 'auth_type',
  username: 'username',
  secret: 'secret',
  commit_url_template: 'commit_url_template',
} as const;

function toInput(values: GitConnectionValues): GitConnectionInput {
  const needsCredentials = values.auth_type !== 'none';
  return {
    name: values.name,
    repo_url: values.repo_url,
    auth_type: values.auth_type,
    username: needsCredentials ? values.username : null,
    // Empty keeps the saved secret, so only send a new value.
    ...(needsCredentials && values.secret ? { secret: values.secret } : {}),
    commit_url_template: values.commit_url_template || null,
  };
}

interface Props {
  connection: GitConnection | null;
  /** Called after a save; a new connection keeps the form open in edit mode. */
  onSaved: (connection: GitConnection) => void;
  onClose: () => void;
  /** A new connection is created for this organization instead of for the user. */
  organizationId?: string;
}

export function GitConnectionForm({ connection, onSaved, onClose, organizationId }: Props) {
  const save = useSaveGitConnection();
  const test = useTestGitConnection();
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<GitTestResult | null>(null);
  // Prefill the username for the detected host until the user types their own.
  const usernameEdited = useRef(Boolean(connection));
  const hasSavedSecret = useRef(Boolean(connection?.has_secret));
  hasSavedSecret.current = Boolean(connection?.has_secret);

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    setError,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<GitConnectionValues>({
    // Read at validation time: after the first save a secret is stored, so it may stay empty.
    resolver: (values, context, options) =>
      zodResolver(gitConnectionSchema({ hasSavedSecret: hasSavedSecret.current }))(
        values,
        context,
        options,
      ),
    defaultValues: {
      name: connection?.name ?? '',
      repo_url: connection?.repo_url ?? '',
      auth_type: connection?.auth_type ?? 'token',
      username: connection?.username ?? '',
      secret: '',
      commit_url_template: connection?.commit_url_template ?? '',
    },
  });

  const repoUrl = watch('repo_url');
  const authType = watch('auth_type');
  const host = detectHost(repoUrl);

  useEffect(() => {
    if (!usernameEdited.current) {
      setValue('username', DEFAULT_USERNAMES[host] ?? '', { shouldDirty: true });
    }
  }, [host, setValue]);

  const submit = (andTest: boolean) =>
    handleSubmit(async (values) => {
      setFormError(null);
      setTestResult(null);
      let saved: GitConnection;
      try {
        const body = connection ? toInput(values) : { ...toInput(values), organization_id: organizationId };
        saved = await save.mutateAsync({ id: connection?.id, body });
      } catch (error) {
        setFormError(applyServerErrors(error, setError, FIELDS));
        return;
      }
      reset({ ...values, secret: '' });
      onSaved(saved);
      if (andTest) await runTest(saved.id);
      else notifications.show({ color: 'teal', message: `Saved "${saved.name}".` });
    });

  const runTest = async (id: string) => {
    setTestResult(null);
    try {
      setTestResult(await test.mutateAsync(id));
    } catch (error) {
      setTestResult({ ok: false, branches: [], default_branch: null, error: errorMessage(error) });
    }
  };

  const canTestSaved = connection !== null && !isDirty;

  return (
    <form onSubmit={submit(false)} noValidate>
      <Stack>
        {formError && (
          <Alert color="red" variant="light" role="alert">
            {formError}
          </Alert>
        )}
        <TextInput label="Name" placeholder="Web app repository" error={errors.name?.message} {...register('name')} />
        <TextInput
          label="Repository URL"
          placeholder="https://dev.azure.com/acme/project/_git/repo"
          description={repoUrl ? `Detected host: ${HOST_LABELS[host]}` : 'The HTTPS clone URL.'}
          error={errors.repo_url?.message}
          {...register('repo_url')}
        />
        <Controller
          control={control}
          name="auth_type"
          render={({ field }) => (
            <Stack gap={4}>
              <Text size="sm" fw={500} id="auth-type-label">
                Authentication
              </Text>
              <SegmentedControl
                aria-labelledby="auth-type-label"
                value={field.value}
                onChange={(value) => field.onChange(value)}
                data={[
                  { value: 'token', label: 'Token' },
                  { value: 'basic', label: 'Password' },
                  { value: 'none', label: 'Public' },
                ]}
              />
            </Stack>
          )}
        />
        {authType !== 'none' && (
          <>
            <TextInput
              label="Username"
              error={errors.username?.message}
              {...register('username', {
                onChange: () => {
                  usernameEdited.current = true;
                },
              })}
            />
            <SecretInput
              label={authType === 'token' ? 'Access token' : 'Account password'}
              saved={Boolean(connection?.has_secret)}
              description={SECRET_HINTS[host]}
              error={errors.secret?.message}
              {...register('secret')}
            />
          </>
        )}
        <TextInput
          label="Commit link (optional)"
          placeholder={connection?.commit_url_pattern || 'https://git.example.com/acme/repo/commit/{sha}'}
          description="Used for links in comments. Leave empty to use the usual link for Azure Repos, GitHub, GitLab and Bitbucket."
          error={errors.commit_url_template?.message}
          {...register('commit_url_template')}
        />

        {testResult && <GitTestResultView result={testResult} />}

        <Group justify="space-between">
          <Button
            variant="default"
            loading={test.isPending}
            disabled={isSubmitting}
            onClick={canTestSaved ? () => void runTest(connection.id) : submit(true)}
          >
            {canTestSaved ? 'Test connection' : 'Save and test'}
          </Button>
          <Group gap="sm">
            <Button variant="subtle" onClick={onClose}>
              Close
            </Button>
            <Button type="submit" loading={isSubmitting && !test.isPending} disabled={!isDirty && connection !== null}>
              Save
            </Button>
          </Group>
        </Group>
      </Stack>
    </form>
  );
}
