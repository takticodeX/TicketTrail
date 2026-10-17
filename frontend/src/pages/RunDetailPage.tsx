import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Chip,
  Code,
  Group,
  Loader,
  Pagination,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import type { ItemAction, SyncRunDetail } from '../api/types';
import { RunStatusBadge } from '../components/RunStatusBadge';
import { useRun, useRunItems } from '../hooks/useRuns';
import { useAzureConnections, useGitConnections, useProject } from '../hooks/useSettings';
import {
  ACTION_COLORS,
  ACTION_LABELS,
  ACTION_ORDER,
  commitUrl,
  formatDateTime,
  isRunActive,
  runDuration,
  workItemUrl,
} from '../lib/runs';

const PAGE_SIZE = 50;
const ALL = 'all';

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text size="lg" fw={600}>
        {value}
      </Text>
    </Paper>
  );
}

function RunSummary({ run }: { run: SyncRunDetail }) {
  const counts = run.counts_by_action;
  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }}>
      <Stat label="Commits scanned" value={run.commits_scanned} />
      <Stat
        label={run.dry_run ? 'Would post' : 'Comments posted'}
        value={run.dry_run ? (counts.would_post ?? 0) : run.comments_posted}
      />
      <Stat label="No reference" value={counts.no_reference ?? 0} />
      <Stat label="Errors" value={run.errors} />
    </SimpleGrid>
  );
}

export function RunDetailPage() {
  const { projectId = '', runId = '' } = useParams();
  const run = useRun(runId);
  const project = useProject(projectId);
  const git = useGitConnections();
  const azure = useAzureConnections();
  const [action, setAction] = useState<ItemAction | null>(null);
  const [page, setPage] = useState(1);
  const items = useRunItems(runId, page, action);

  if (run.isPending) {
    return (
      <Center p="xl">
        <Loader aria-label="Loading" />
      </Center>
    );
  }
  if (run.isError) {
    return (
      <Alert color="red" variant="light" role="alert">
        {errorMessage(run.error)}
      </Alert>
    );
  }

  const gitConnection = git.data?.items.find((c) => c.id === project.data?.git_connection_id);
  const azureConnection = azure.data?.items.find((c) => c.id === project.data?.azure_connection_id);
  const totalPages = items.data ? Math.max(1, Math.ceil(items.data.total / PAGE_SIZE)) : 1;
  const failed = run.data.status === 'failed';

  const refresh = () => {
    void run.refetch();
    void items.refetch();
  };

  const onFilter = (value: string) => {
    setAction(value === ALL ? null : (value as ItemAction));
    setPage(1);
  };

  return (
    <Stack maw={1100}>
      <div>
        <Anchor component={Link} to={`/projects/${projectId}`} size="sm">
          ← {project.data?.name ?? 'Project'}
        </Anchor>
        <Group gap="sm" align="center">
          <Title order={2}>{run.data.dry_run ? 'Dry run' : 'Sync'}</Title>
          <RunStatusBadge status={run.data.status} />
        </Group>
        <Text size="sm" c="dimmed">
          Started {formatDateTime(run.data.started_at ?? run.data.created_at)}
          {runDuration(run.data) && ` · took ${runDuration(run.data)}`}
        </Text>
      </div>

      {isRunActive(run.data) && (
        <Alert color="blue" variant="light" title="The run is in progress">
          <Group justify="space-between">
            <Text size="sm">Refresh to see the latest results.</Text>
            <Button size="xs" variant="light" onClick={refresh} loading={run.isFetching}>
              Refresh
            </Button>
          </Group>
        </Alert>
      )}
      {run.data.error_message && (
        <Alert
          color={failed ? 'red' : 'yellow'}
          variant="light"
          title={failed ? 'The run failed' : 'Warnings'}
          role={failed ? 'alert' : 'status'}
        >
          <Text size="sm" style={{ whiteSpace: 'pre-line' }}>
            {run.data.error_message}
          </Text>
        </Alert>
      )}

      {!failed && <RunSummary run={run.data} />}

      {!failed && (
        <>
          <Chip.Group multiple={false} value={action ?? ALL} onChange={onFilter}>
            <Group gap="xs" aria-label="Filter by action">
              <Chip value={ALL} size="sm">
                All
              </Chip>
              {ACTION_ORDER.filter((a) => (run.data.counts_by_action[a] ?? 0) > 0).map((a) => (
                <Chip key={a} value={a} size="sm">
                  {ACTION_LABELS[a]} ({run.data.counts_by_action[a]})
                </Chip>
              ))}
            </Group>
          </Chip.Group>

          {items.isError && (
            <Alert color="red" variant="light" role="alert">
              {errorMessage(items.error)}
            </Alert>
          )}
          {items.data && items.data.items.length === 0 && (
            <Paper withBorder p="xl" radius="md">
              <Text ta="center" c="dimmed">
                No commits to show.
              </Text>
            </Paper>
          )}
          {items.data && items.data.items.length > 0 && (
            <Paper withBorder radius="md">
              <Table.ScrollContainer minWidth={760}>
                <Table verticalSpacing="xs" highlightOnHover aria-label="Run items">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Commit</Table.Th>
                      <Table.Th>Message</Table.Th>
                      <Table.Th>Work item</Table.Th>
                      <Table.Th>Action</Table.Th>
                      <Table.Th>Detail</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {items.data.items.map((item) => {
                      const link = commitUrl(gitConnection?.commit_url_pattern, item.commit_sha);
                      const sha = <Code>{item.commit_sha.slice(0, 7)}</Code>;
                      return (
                        <Table.Tr key={item.id}>
                          <Table.Td>
                            {link ? (
                              <Anchor href={link} target="_blank" rel="noreferrer" title={item.commit_sha}>
                                {sha}
                              </Anchor>
                            ) : (
                              <span title={item.commit_sha}>{sha}</span>
                            )}
                            <Text size="xs" c="dimmed">
                              {item.branch}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            <Text size="sm" lineClamp={2} maw={420}>
                              {item.commit_subject}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            {item.work_item_id === null ? (
                              '—'
                            ) : azureConnection ? (
                              <Anchor
                                href={workItemUrl(azureConnection, item.work_item_id)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                #{item.work_item_id}
                              </Anchor>
                            ) : (
                              `#${item.work_item_id}`
                            )}
                          </Table.Td>
                          <Table.Td>
                            <Badge color={ACTION_COLORS[item.action]} variant="light" tt="none">
                              {ACTION_LABELS[item.action]}
                            </Badge>
                          </Table.Td>
                          <Table.Td>
                            <Text size="xs" c="dimmed">
                              {item.detail ?? ''}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </Paper>
          )}
          {totalPages > 1 && <Pagination total={totalPages} value={page} onChange={setPage} />}
        </>
      )}
    </Stack>
  );
}
