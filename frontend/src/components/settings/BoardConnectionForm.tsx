import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Button, Group, Stack, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';

import { applyServerErrors, errorMessage } from '../../api/errors';
import type { BoardConnection, BoardConnectionInput, BoardTestResult } from '../../api/types';
import { useSaveBoardConnection, useTestBoardConnection } from '../../hooks/useSettings';
import { boardConnectionSchema, type BoardConnectionValues } from '../../schemas/settings';
import { SecretInput } from '../SecretInput';
import { BoardTestResultView } from './ConnectionTestResult';

const FIELDS = {
  name: 'name',
  url: 'url',
  scope: 'scope',
  secret: 'secret',
} as const;

function toInput(values: BoardConnectionValues): BoardConnectionInput {
  return {
    name: values.name,
    url: values.url,
    scope: values.scope,
    ...(values.secret ? { secret: values.secret } : {}),
  };
}

interface Props {
  connection: BoardConnection | null;
  onSaved: (connection: BoardConnection) => void;
  onClose: () => void;
  /** A new connection is created for this organization instead of for the user. */
  organizationId?: string;
}

export function BoardConnectionForm({ connection, onSaved, onClose, organizationId }: Props) {
  const save = useSaveBoardConnection();
  const test = useTestBoardConnection();
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<BoardTestResult | null>(null);
  const hasSavedSecret = useRef(Boolean(connection?.has_secret));
  hasSavedSecret.current = Boolean(connection?.has_secret);

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<BoardConnectionValues>({
    // Read at validation time: after the first save a token is stored, so it may stay empty.
    resolver: (values, context, options) =>
      zodResolver(boardConnectionSchema({ hasSavedSecret: hasSavedSecret.current }))(
        values,
        context,
        options,
      ),
    defaultValues: {
      name: connection?.name ?? '',
      url: connection?.url ?? '',
      scope: connection?.scope ?? '',
      secret: '',
    },
  });

  const runTest = async (id: string) => {
    setTestResult(null);
    try {
      setTestResult(await test.mutateAsync(id));
    } catch (error) {
      setTestResult({ ok: false, scope_name: null, error: errorMessage(error) });
    }
  };

  const submit = (andTest: boolean) =>
    handleSubmit(async (values) => {
      setFormError(null);
      setTestResult(null);
      let saved: BoardConnection;
      try {
        const body = connection
          ? toInput(values)
          : { ...toInput(values), kind: 'azure' as const, organization_id: organizationId };
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

  const canTestSaved = connection !== null && !isDirty;

  return (
    <form onSubmit={submit(false)} noValidate>
      <Stack>
        {formError && (
          <Alert color="red" variant="light" role="alert">
            {formError}
          </Alert>
        )}
        <TextInput label="Name" placeholder="Acme board" error={errors.name?.message} {...register('name')} />
        <TextInput
          label="Organization URL"
          placeholder="https://dev.azure.com/acme"
          error={errors.url?.message}
          {...register('url')}
        />
        <TextInput
          label="Project"
          description="The Azure DevOps project whose work items get the comments."
          error={errors.scope?.message}
          {...register('scope')}
        />
        <SecretInput
          label="Personal access token"
          saved={Boolean(connection?.has_secret)}
          description="Needs the Work Items (Read & Write) scope, and nothing more."
          error={errors.secret?.message}
          {...register('secret')}
        />

        {testResult && <BoardTestResultView result={testResult} />}

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
