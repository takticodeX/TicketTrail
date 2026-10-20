import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Button, Group, Stack, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';

import { applyServerErrors, errorMessage } from '../../api/errors';
import type { AzureConnection, AzureConnectionInput, AzureTestResult } from '../../api/types';
import { useSaveAzureConnection, useTestAzureConnection } from '../../hooks/useSettings';
import { azureConnectionSchema, type AzureConnectionValues } from '../../schemas/settings';
import { SecretInput } from '../SecretInput';
import { AzureTestResultView } from './ConnectionTestResult';

const FIELDS = {
  name: 'name',
  organization_url: 'organization_url',
  azure_project: 'azure_project',
  pat: 'pat',
} as const;

function toInput(values: AzureConnectionValues): AzureConnectionInput {
  return {
    name: values.name,
    organization_url: values.organization_url,
    azure_project: values.azure_project,
    ...(values.pat ? { pat: values.pat } : {}),
  };
}

interface Props {
  connection: AzureConnection | null;
  onSaved: (connection: AzureConnection) => void;
  onClose: () => void;
  /** A new connection is created for this organization instead of for the user. */
  organizationId?: string;
}

export function AzureConnectionForm({ connection, onSaved, onClose, organizationId }: Props) {
  const save = useSaveAzureConnection();
  const test = useTestAzureConnection();
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<AzureTestResult | null>(null);
  const hasSavedSecret = useRef(Boolean(connection?.has_secret));
  hasSavedSecret.current = Boolean(connection?.has_secret);

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<AzureConnectionValues>({
    // Read at validation time: after the first save a PAT is stored, so it may stay empty.
    resolver: (values, context, options) =>
      zodResolver(azureConnectionSchema({ hasSavedSecret: hasSavedSecret.current }))(
        values,
        context,
        options,
      ),
    defaultValues: {
      name: connection?.name ?? '',
      organization_url: connection?.organization_url ?? '',
      azure_project: connection?.azure_project ?? '',
      pat: '',
    },
  });

  const runTest = async (id: string) => {
    setTestResult(null);
    try {
      setTestResult(await test.mutateAsync(id));
    } catch (error) {
      setTestResult({ ok: false, project_name: null, error: errorMessage(error) });
    }
  };

  const submit = (andTest: boolean) =>
    handleSubmit(async (values) => {
      setFormError(null);
      setTestResult(null);
      let saved: AzureConnection;
      try {
        const body = connection ? toInput(values) : { ...toInput(values), organization_id: organizationId };
        saved = await save.mutateAsync({ id: connection?.id, body });
      } catch (error) {
        setFormError(applyServerErrors(error, setError, FIELDS));
        return;
      }
      reset({ ...values, pat: '' });
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
          error={errors.organization_url?.message}
          {...register('organization_url')}
        />
        <TextInput
          label="Project"
          description="The Azure DevOps project whose work items get the comments."
          error={errors.azure_project?.message}
          {...register('azure_project')}
        />
        <SecretInput
          label="Personal access token"
          saved={Boolean(connection?.has_secret)}
          description="Needs the Work Items (Read & Write) scope, and nothing more."
          error={errors.pat?.message}
          {...register('pat')}
        />

        {testResult && <AzureTestResultView result={testResult} />}

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
