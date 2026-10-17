import { zodResolver } from '@hookform/resolvers/zod';
import {
  Alert,
  Anchor,
  Button,
  Center,
  Checkbox,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Stepper,
  TagsInput,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMemo, useState } from 'react';
import { Controller, useForm, type FieldPath } from 'react-hook-form';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { applyServerErrors, errorMessage } from '../../api/errors';
import type { GitTestResult, Project } from '../../api/types';
import { GitTestResultView } from '../../components/settings/ConnectionTestResult';
import { DEFAULT_SAMPLES, PatternTester } from '../../components/settings/PatternTester';
import { ScheduleField } from '../../components/settings/ScheduleField';
import { TemplateEditor } from '../../components/settings/TemplateEditor';
import { useAuth } from '../../hooks/useAuth';
import {
  useAzureConnections,
  useGitConnections,
  useProject,
  useSaveProject,
  useTestGitConnection,
} from '../../hooks/useSettings';
import { projectSchema, type ProjectValues } from '../../schemas/settings';
import { FIELD_STEP, sampleCommit, toFormValues, toProjectInput } from './projectForm';

const STEPS: { label: string; fields: FieldPath<ProjectValues>[] }[] = [
  { label: 'Repository', fields: ['name', 'git_connection_id'] },
  { label: 'Branches', fields: ['branches'] },
  { label: 'Board', fields: ['azure_connection_id'] },
  { label: 'Ticket pattern', fields: ['ticket_pattern'] },
  { label: 'Comment', fields: ['comment_template'] },
  { label: 'Start point', fields: ['start_mode', 'start_date', 'start_sha'] },
  { label: 'Schedule', fields: ['schedule_cron', 'schedule_enabled'] },
];

const SERVER_FIELDS = Object.fromEntries(
  Object.keys(FIELD_STEP).map((field) => [field, field === 'start_from' ? 'start_date' : field]),
) as Record<string, FieldPath<ProjectValues>>;

export function ProjectWizardPage() {
  const { projectId } = useParams();
  const project = useProject(projectId);

  if (projectId && project.isPending) {
    return (
      <Center p="xl">
        <Loader aria-label="Loading" />
      </Center>
    );
  }
  if (projectId && project.isError) {
    return (
      <Alert color="red" variant="light" role="alert">
        {errorMessage(project.error)}
      </Alert>
    );
  }
  return <ProjectWizard key={projectId ?? 'new'} project={project.data} />;
}

function ProjectWizard({ project }: { project: Project | undefined }) {
  const editing = project !== undefined;
  const navigate = useNavigate();
  const { user } = useAuth();
  const gitConnections = useGitConnections();
  const azureConnections = useAzureConnections();
  const save = useSaveProject();
  const loadBranches = useTestGitConnection();

  const [active, setActive] = useState(0);
  const [samples, setSamples] = useState(DEFAULT_SAMPLES);
  const [branchResult, setBranchResult] = useState<GitTestResult | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    control,
    handleSubmit,
    watch,
    trigger,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ProjectValues>({
    resolver: zodResolver(projectSchema),
    defaultValues: toFormValues(project),
  });

  const gitId = watch('git_connection_id');
  const branches = watch('branches');
  const startMode = watch('start_mode');
  const pattern = watch('ticket_pattern');
  const gitConnection = gitConnections.data?.items.find((c) => c.id === gitId);
  const previewBranch = branches[0] ?? branchResult?.default_branch ?? 'main';
  const sample = useMemo(
    () => sampleCommit(gitConnection, previewBranch, samples),
    [gitConnection, previewBranch, samples],
  );

  const next = async () => {
    if (await trigger(STEPS[active]?.fields ?? [])) setActive((step) => Math.min(step + 1, STEPS.length - 1));
  };

  const onSubmit = handleSubmit(
    async (values) => {
      setFormError(null);
      try {
        const saved = await save.mutateAsync({ id: project?.id, body: toProjectInput(values) });
        notifications.show({ color: 'teal', message: `Saved "${saved.name}".` });
        navigate('/settings/projects');
      } catch (error) {
        setFormError(applyServerErrors(error, setError, SERVER_FIELDS));
      }
    },
    (invalid) => {
      // Jump to the first step that has an error.
      const steps = Object.keys(invalid).map((field) => FIELD_STEP[field] ?? 0);
      if (steps.length > 0) setActive(Math.min(...steps));
    },
  );

  const onLoadBranches = async () => {
    if (!gitId) return;
    setBranchResult(null);
    try {
      setBranchResult(await loadBranches.mutateAsync(gitId));
    } catch (error) {
      setBranchResult({ ok: false, branches: [], default_branch: null, error: errorMessage(error) });
    }
  };

  const gitOptions = (gitConnections.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }));
  const azureOptions = (azureConnections.data?.items ?? []).map((c) => ({
    value: c.id,
    label: `${c.name} (${c.azure_project})`,
  }));
  const isLast = active === STEPS.length - 1;

  return (
    <Stack maw={860}>
      <div>
        <Anchor component={Link} to="/settings/projects" size="sm">
          ← Projects
        </Anchor>
        <Title order={2}>{editing ? `Edit ${project.name}` : 'New project'}</Title>
      </div>
      <form onSubmit={onSubmit} noValidate>
        <Paper withBorder radius="md" p="lg">
          <Stack gap="lg">
            {formError && (
              <Alert color="red" variant="light" role="alert">
                {formError}
              </Alert>
            )}
            <Stepper
              active={active}
              onStepClick={setActive}
              allowNextStepsSelect={editing}
              size="sm"
              wrap
            >
              <Stepper.Step label="Repository">
                <Stack pt="md">
                  <TextInput label="Project name" error={errors.name?.message} {...register('name')} />
                  <Controller
                    control={control}
                    name="git_connection_id"
                    render={({ field }) => (
                      <Select
                        label="Git connection"
                        placeholder="Pick a repository"
                        data={gitOptions}
                        value={field.value || null}
                        onChange={(value) => {
                          field.onChange(value ?? '');
                          setBranchResult(null);
                        }}
                        error={errors.git_connection_id?.message}
                        nothingFoundMessage="No Git connections"
                      />
                    )}
                  />
                  {gitConnections.data?.items.length === 0 && (
                    <Text size="sm">
                      No Git connections yet.{' '}
                      <Anchor component={Link} to="/settings/git">
                        Add one first
                      </Anchor>
                      .
                    </Text>
                  )}
                </Stack>
              </Stepper.Step>

              <Stepper.Step label="Branches">
                <Stack pt="md">
                  <Group align="flex-end">
                    <Button variant="default" onClick={() => void onLoadBranches()} loading={loadBranches.isPending} disabled={!gitId}>
                      Load branches from the repository
                    </Button>
                  </Group>
                  {branchResult && <GitTestResultView result={branchResult} />}
                  <Controller
                    control={control}
                    name="branches"
                    render={({ field }) => (
                      <TagsInput
                        label="Branches to sync"
                        description={`Leave empty to sync only the default branch${
                          branchResult?.default_branch ? ` (${branchResult.default_branch})` : ''
                        }.`}
                        placeholder="Type or pick a branch"
                        data={branchResult?.branches ?? []}
                        value={field.value}
                        onChange={field.onChange}
                        clearable
                        error={errors.branches?.message}
                      />
                    )}
                  />
                </Stack>
              </Stepper.Step>

              <Stepper.Step label="Board">
                <Stack pt="md">
                  <Controller
                    control={control}
                    name="azure_connection_id"
                    render={({ field }) => (
                      <Select
                        label="Azure connection"
                        placeholder="Pick a board"
                        data={azureOptions}
                        value={field.value || null}
                        onChange={(value) => field.onChange(value ?? '')}
                        error={errors.azure_connection_id?.message}
                        nothingFoundMessage="No Azure connections"
                      />
                    )}
                  />
                  {azureConnections.data?.items.length === 0 && (
                    <Text size="sm">
                      No Azure connections yet.{' '}
                      <Anchor component={Link} to="/settings/azure">
                        Add one first
                      </Anchor>
                      .
                    </Text>
                  )}
                </Stack>
              </Stepper.Step>

              <Stepper.Step label="Ticket pattern">
                <Stack pt="md">
                  <TextInput
                    label="Ticket pattern"
                    description="A Python regular expression with one capture group for the work item ID. Matching ignores case. Default: AB#(\d+)"
                    ff="monospace"
                    error={errors.ticket_pattern?.message}
                    {...register('ticket_pattern')}
                  />
                  <PatternTester pattern={pattern} samples={samples} onSamplesChange={setSamples} />
                </Stack>
              </Stepper.Step>

              <Stepper.Step label="Comment">
                <Stack pt="md">
                  <Controller
                    control={control}
                    name="comment_template"
                    render={({ field }) => (
                      <TemplateEditor
                        value={field.value}
                        onChange={field.onChange}
                        error={errors.comment_template?.message}
                        sample={sample}
                      />
                    )}
                  />
                </Stack>
              </Stepper.Step>

              <Stepper.Step label="Start point">
                <Stack pt="md">
                  <Controller
                    control={control}
                    name="start_mode"
                    render={({ field }) => (
                      <Stack gap={4}>
                        <Text size="sm" fw={500} id="start-mode-label">
                          First sync starts from
                        </Text>
                        <SegmentedControl
                          aria-labelledby="start-mode-label"
                          value={field.value}
                          onChange={field.onChange}
                          data={[
                            { value: 'all', label: 'Full history' },
                            { value: 'date', label: 'A date' },
                            { value: 'sha', label: 'A commit' },
                          ]}
                        />
                      </Stack>
                    )}
                  />
                  {startMode === 'date' && (
                    <TextInput type="date" label="Start date" error={errors.start_date?.message} {...register('start_date')} />
                  )}
                  {startMode === 'sha' && (
                    <TextInput
                      label="Start commit"
                      description="Commits after this one are synced."
                      ff="monospace"
                      error={errors.start_sha?.message}
                      {...register('start_sha')}
                    />
                  )}
                  <Checkbox
                    label="Include merge commits"
                    description="Off by default: merge commits usually repeat what their branch already posted."
                    {...register('include_merge_commits')}
                  />
                  <Checkbox
                    label="Dry run by default"
                    description="Sync now only shows what would be posted, until you turn this off."
                    {...register('dry_run_default')}
                  />
                </Stack>
              </Stepper.Step>

              <Stepper.Step label="Schedule">
                <Stack pt="md">
                  <Controller
                    control={control}
                    name="schedule_enabled"
                    render={({ field: enabled }) => (
                      <Controller
                        control={control}
                        name="schedule_cron"
                        render={({ field: cron }) => (
                          <ScheduleField
                            cron={cron.value}
                            onCronChange={cron.onChange}
                            enabled={enabled.value}
                            onEnabledChange={enabled.onChange}
                            error={errors.schedule_cron?.message}
                            timeZone={user?.timezone ?? 'UTC'}
                          />
                        )}
                      />
                    )}
                  />
                  <Text size="xs" c="dimmed">
                    Scheduled runs follow the Dry run by default setting. Changes apply within a
                    minute.
                  </Text>
                </Stack>
              </Stepper.Step>
            </Stepper>

            <Group justify="space-between">
              <Button variant="default" onClick={() => setActive((step) => step - 1)} disabled={active === 0}>
                Back
              </Button>
              <Group gap="sm">
                {!isLast && (
                  <Button variant={editing ? 'default' : 'filled'} onClick={() => void next()}>
                    Next
                  </Button>
                )}
                {(isLast || editing) && (
                  <Button type="submit" loading={isSubmitting}>
                    {editing ? 'Save changes' : 'Create project'}
                  </Button>
                )}
              </Group>
            </Group>
          </Stack>
        </Paper>
      </form>
    </Stack>
  );
}
