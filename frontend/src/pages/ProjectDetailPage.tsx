import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Pagination,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import type { SyncRun } from '../api/types';
import { confirmDelete } from '../components/confirmDelete';
import { RoleBadge, SharingLine } from '../components/ProjectAccess';
import { RunStatusBadge } from '../components/RunStatusBadge';
import { ShareDrawer } from '../components/ShareDrawer';
import { SyncNowButton } from '../components/SyncNowButton';
import { useAuth } from '../hooks/useAuth';
import { useDryRun } from '../hooks/useDryRun';
import { useClearDryRuns, useDeleteRun, useRuns } from '../hooks/useRuns';
import { useProject } from '../hooks/useSettings';
import { useRemoveShare } from '../hooks/useSharing';
import { canEdit, canManageRun, isOwner } from '../lib/access';
import { formatDateTime, isRunActive, runDuration } from '../lib/runs';
import { formatRunTime } from '../lib/schedule';

const PAGE_SIZE = 20;

export function ProjectDetailPage() {
  const { projectId = '' } = useParams();
  const { user } = useAuth();
  const timeZone = user?.timezone ?? 'UTC';
  const navigate = useNavigate();
  const project = useProject(projectId);
  const [page, setPage] = useState(1);
  const [sharing, setSharing] = useState(false);
  const runs = useRuns(projectId, page);
  const dryRun = useDryRun(projectId);
  const deleteRun = useDeleteRun(projectId);
  const clearDryRuns = useClearDryRuns(projectId);
  const leave = useRemoveShare(projectId);

  if (project.isPending) {
    return (
      <Center p="xl">
        <Loader aria-label="Loading" />
      </Center>
    );
  }
  if (project.isError) {
    return (
      <Alert color="red" variant="light" role="alert">
        {errorMessage(project.error)}
      </Alert>
    );
  }

  const gitConnection = project.data.git_connection;
  const azureConnection = project.data.azure_connection;
  const editable = canEdit(project.data);

  const onDeleteRun = (run: SyncRun) =>
    confirmDelete({
      title: run.dry_run ? 'Delete dry run' : 'Delete run',
      message:
        'Remove this run and its commit list from the history? Nothing changes in Azure DevOps, ' +
        'and comments already posted are never posted again.',
      onConfirm: () =>
        deleteRun.mutate(run.id, {
          onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
        }),
    });

  const onClearDryRuns = () =>
    confirmDelete({
      title: 'Clear dry runs',
      message: 'Delete every finished dry run of this project from the history? Real syncs stay.',
      onConfirm: () =>
        clearDryRuns.mutate(undefined, {
          onSuccess: ({ deleted }) =>
            notifications.show({
              color: 'teal',
              message: `Deleted ${deleted} dry ${deleted === 1 ? 'run' : 'runs'}.`,
            }),
          onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
        }),
    });

  const onLeave = () =>
    modals.openConfirmModal({
      title: 'Leave this project?',
      children: (
        <Text size="sm">
          You lose access to "{project.data.name}" and its runs, until{' '}
          {project.data.owner?.display_name ?? 'the owner'} shares it with you again.
        </Text>
      ),
      labels: { confirm: 'Leave', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () => {
        if (!user) return;
        leave.mutate(user.id, {
          onSuccess: () => navigate('/'),
          onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
        });
      },
    });

  const totalPages = runs.data ? Math.max(1, Math.ceil(runs.data.total / PAGE_SIZE)) : 1;

  return (
    <Stack maw={1100}>
      <Group justify="space-between" align="flex-start">
        <div>
          <Group gap="xs">
            <Title order={2}>{project.data.name}</Title>
            <RoleBadge project={project.data} />
          </Group>
          <Text size="sm" c="dimmed">
            {gitConnection?.name ?? '…'}
            {' · '}
            {project.data.branches.length > 0 ? project.data.branches.join(', ') : 'default branch'}
            {' → '}
            {azureConnection ? `${azureConnection.name} (${azureConnection.azure_project})` : '…'}
          </Text>
          <SharingLine project={project.data} />
        </div>
        <Group gap="sm">
          {isOwner(project.data) ? (
            <Button variant="default" onClick={() => setSharing(true)}>
              Share
            </Button>
          ) : (
            <Button variant="subtle" color="red" onClick={onLeave}>
              Leave
            </Button>
          )}
          {editable && (
            <Button variant="default" component={Link} to={`/settings/projects/${projectId}`}>
              Settings
            </Button>
          )}
          <Button variant="default" onClick={dryRun.start} loading={dryRun.pending}>
            Dry run
          </Button>
          {editable && <SyncNowButton project={project.data} onDryRun={dryRun.start} />}
        </Group>
      </Group>
      {isOwner(project.data) && (
        <ShareDrawer project={project.data} opened={sharing} onClose={() => setSharing(false)} />
      )}
      <Text size="sm" c="dimmed">
        A dry run lists which comments would be posted, without changing anything in Azure DevOps.
        {editable ? ' Sync now posts them.' : ' Only an editor can post them.'}
        {project.data.next_run_at &&
          ` Next scheduled run: ${formatRunTime(new Date(project.data.next_run_at), timeZone)}.`}
      </Text>

      <Group justify="space-between">
        <Title order={4}>Run history</Title>
        {editable && runs.data?.items.some((run) => run.dry_run && !isRunActive(run)) && (
          <Button size="xs" variant="subtle" color="red" onClick={onClearDryRuns} loading={clearDryRuns.isPending}>
            Clear dry runs
          </Button>
        )}
      </Group>
      {runs.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(runs.error)}
        </Alert>
      )}
      {runs.data && runs.data.items.length === 0 && (
        <Paper withBorder p="xl" radius="md">
          <Text ta="center" c="dimmed">
            No runs yet. Start a dry run to see what TicketTrail would post.
          </Text>
        </Paper>
      )}
      {runs.data && runs.data.items.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={720}>
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Started</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Type</Table.Th>
                  <Table.Th ta="right">Commits</Table.Th>
                  <Table.Th ta="right">Comments</Table.Th>
                  <Table.Th ta="right">Errors</Table.Th>
                  <Table.Th>Duration</Table.Th>
                  <Table.Th aria-label="Actions" />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {runs.data.items.map((run) => (
                  <Table.Tr key={run.id}>
                    <Table.Td>
                      <Anchor component={Link} to={`/projects/${projectId}/runs/${run.id}`}>
                        {formatDateTime(run.started_at ?? run.created_at)}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>
                      <RunStatusBadge status={run.status} />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        <Text size="sm">{run.trigger === 'manual' ? 'Manual' : 'Scheduled'}</Text>
                        {run.dry_run && (
                          <Badge size="xs" variant="outline">
                            Dry run
                          </Badge>
                        )}
                      </Group>
                      {run.triggered_by && (
                        <Text size="xs" c="dimmed">
                          by {run.triggered_by.display_name}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right">{run.commits_scanned}</Table.Td>
                    <Table.Td ta="right">{run.comments_posted}</Table.Td>
                    <Table.Td ta="right">{run.errors}</Table.Td>
                    <Table.Td>{runDuration(run) ?? '—'}</Table.Td>
                    <Table.Td>
                      {!isRunActive(run) && canManageRun(project.data, run, user?.id) && (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="red"
                          aria-label={`Delete run of ${formatDateTime(run.started_at ?? run.created_at)}`}
                          onClick={() => onDeleteRun(run)}
                        >
                          Delete
                        </Button>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {totalPages > 1 && <Pagination total={totalPages} value={page} onChange={setPage} />}
    </Stack>
  );
}
