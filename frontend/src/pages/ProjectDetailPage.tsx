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
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import { RunStatusBadge } from '../components/RunStatusBadge';
import { SyncNowButton } from '../components/SyncNowButton';
import { useRuns, useStartSync } from '../hooks/useRuns';
import { useAzureConnections, useGitConnections, useProject } from '../hooks/useSettings';
import { formatDateTime, runDuration } from '../lib/runs';

const PAGE_SIZE = 20;

export function ProjectDetailPage() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const project = useProject(projectId);
  const git = useGitConnections();
  const azure = useAzureConnections();
  const [page, setPage] = useState(1);
  const runs = useRuns(projectId, page);
  const startSync = useStartSync(projectId);

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

  const gitConnection = git.data?.items.find((c) => c.id === project.data.git_connection_id);
  const azureConnection = azure.data?.items.find((c) => c.id === project.data.azure_connection_id);

  const onDryRun = () =>
    startSync.mutate(true, {
      onSuccess: ({ run_id }) => navigate(`/projects/${projectId}/runs/${run_id}`),
      onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
    });

  const totalPages = runs.data ? Math.max(1, Math.ceil(runs.data.total / PAGE_SIZE)) : 1;

  return (
    <Stack maw={1100}>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{project.data.name}</Title>
          <Text size="sm" c="dimmed">
            {gitConnection?.name ?? '…'}
            {' · '}
            {project.data.branches.length > 0 ? project.data.branches.join(', ') : 'default branch'}
            {' → '}
            {azureConnection ? `${azureConnection.name} (${azureConnection.azure_project})` : '…'}
          </Text>
        </div>
        <Group gap="sm">
          <Button variant="default" component={Link} to={`/settings/projects/${projectId}`}>
            Settings
          </Button>
          <Button variant="default" onClick={onDryRun} loading={startSync.isPending}>
            Dry run
          </Button>
          <SyncNowButton project={project.data} runs={runs.data?.items} onDryRun={onDryRun} />
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        A dry run lists which comments would be posted, without changing anything in Azure DevOps.
        Sync now posts them.
      </Text>

      <Group justify="space-between">
        <Title order={4}>Run history</Title>
        <Button size="xs" variant="subtle" onClick={() => void runs.refetch()} loading={runs.isFetching}>
          Refresh
        </Button>
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
                    </Table.Td>
                    <Table.Td ta="right">{run.commits_scanned}</Table.Td>
                    <Table.Td ta="right">{run.comments_posted}</Table.Td>
                    <Table.Td ta="right">{run.errors}</Table.Td>
                    <Table.Td>{runDuration(run) ?? '—'}</Table.Td>
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
