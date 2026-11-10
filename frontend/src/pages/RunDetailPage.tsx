import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Checkbox,
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
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import type { ItemAction, SyncRunDetail, SyncRunItem } from '../api/types';
import { confirmDelete } from '../components/confirmDelete';
import { RunStatusBadge } from '../components/RunStatusBadge';
import { WorkItemPicker } from '../components/WorkItemPicker';
import {
  useCancelRun,
  useDeleteRun,
  usePostSelected,
  useRun,
  useRunItems,
  useSetItemSelected,
  useSetItemWorkItem,
} from '../hooks/useRuns';
import { useAuth } from '../hooks/useAuth';
import { useProject } from '../hooks/useSettings';
import { canEdit, canManageRun } from '../lib/access';
import { BOARD_LABELS, workItemUrl } from '../lib/boards';
import {
  ACTION_COLORS,
  ACTION_LABELS,
  ACTION_ORDER,
  commitUrl,
  formatDateTime,
  isRunActive,
  runDuration,
} from '../lib/runs';

const PAGE_SIZE = 50;
const ALL = 'all';
// Dry-run rows a review may point at another work item.
const LINKABLE: ReadonlySet<ItemAction> = new Set(['no_reference', 'skipped_not_found', 'would_post', 'excluded']);

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
      <Stat label="Skipped" value={run.skipped} />
      <Stat label="Errors" value={run.errors} />
    </SimpleGrid>
  );
}

export function RunDetailPage() {
  const { projectId = '', runId = '' } = useParams();
  const run = useRun(runId);
  const project = useProject(projectId);
  const { user } = useAuth();
  const [action, setAction] = useState<ItemAction | null>(null);
  const [page, setPage] = useState(1);
  const live = run.data ? isRunActive(run.data) : false;
  const items = useRunItems(runId, page, action, live);
  const cancel = useCancelRun(runId);
  const remove = useDeleteRun(projectId);
  const setWorkItem = useSetItemWorkItem(runId);
  const setSelected = useSetItemSelected(runId);
  const postSelected = usePostSelected(projectId);
  // The row whose work item is being changed in the review.
  const [editing, setEditing] = useState<string | null>(null);
  const navigate = useNavigate();

  // Reload the items once more when the run finishes, so the last ones show up.
  const status = run.data?.status;
  const refetchItems = items.refetch;
  useEffect(() => {
    if (status && !live) void refetchItems();
  }, [status, live, refetchItems]);

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

  const gitConnection = project.data?.git_connection;
  const boardConnection = project.data?.board_connection;
  const boardLabel = boardConnection ? BOARD_LABELS[boardConnection.kind] : 'the board';
  const manageable = project.data ? canManageRun(project.data, run.data, user?.id) : false;
  const totalPages = items.data ? Math.max(1, Math.ceil(items.data.total / PAGE_SIZE)) : 1;
  const failed = run.data.status === 'failed';
  const cancelled = run.data.status === 'cancelled';
  // A finished dry run can be reviewed by whoever may post: editors and owners.
  const reviewable =
    run.data.dry_run &&
    (run.data.status === 'success' || run.data.status === 'partial') &&
    project.data !== undefined &&
    canEdit(project.data);
  const selectedCount = run.data.counts_by_action.would_post ?? 0;
  const showError = (error: unknown) => notifications.show({ color: 'red', message: errorMessage(error) });

  const pick = (item: SyncRunItem, workItemId: string) =>
    setWorkItem.mutate(
      { itemId: item.id, workItemId },
      { onSuccess: () => setEditing(null), onError: showError },
    );

  const onPostSelected = () =>
    modals.openConfirmModal({
      title: 'Post the selected commits?',
      children: (
        <Text size="sm">
          {selectedCount} {selectedCount === 1 ? 'comment is' : 'comments are'} posted to {boardLabel}, exactly as
          selected here. Deselected rows are never posted, by this or any later run. Nothing is ever posted twice.
        </Text>
      ),
      labels: { confirm: 'Post selected', cancel: 'Cancel' },
      onConfirm: () =>
        postSelected.mutate(runId, {
          onSuccess: ({ run_id }) => navigate(`/projects/${projectId}/runs/${run_id}`),
          onError: showError,
        }),
    });

  const onDelete = () =>
    confirmDelete({
      title: run.data.dry_run ? 'Delete dry run' : 'Delete run',
      message:
        `Remove this run and its commit list from the history? Nothing changes in ${boardLabel}, ` +
        'and comments already posted are never posted again.',
      onConfirm: () =>
        remove.mutate(runId, {
          onSuccess: () => navigate(`/projects/${projectId}`),
          onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
        }),
    });

  const onCancel = () =>
    modals.openConfirmModal({
      title: 'Cancel this run?',
      children: (
        <Text size="sm">
          It stops after the commit it is working on. Comments already posted stay, and the next
          run continues from there.
        </Text>
      ),
      labels: { confirm: 'Cancel run', cancel: 'Keep running' },
      confirmProps: { color: 'red' },
      onConfirm: () =>
        cancel.mutate(undefined, {
          onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
        }),
    });

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
        <Group justify="space-between" align="center">
          <Group gap="sm" align="center">
            <Title order={2}>{run.data.dry_run ? 'Dry run' : 'Sync'}</Title>
            <RunStatusBadge status={run.data.status} />
          </Group>
          <Group gap="xs">
            {reviewable && (
              <Button size="xs" onClick={onPostSelected} disabled={selectedCount === 0} loading={postSelected.isPending}>
                Post selected ({selectedCount})
              </Button>
            )}
            {!live && manageable && (
              <Button size="xs" variant="subtle" color="red" onClick={onDelete} loading={remove.isPending}>
                Delete run
              </Button>
            )}
          </Group>
        </Group>
        <Text size="sm" c="dimmed">
          Started {formatDateTime(run.data.started_at ?? run.data.created_at)}
          {runDuration(run.data) && ` · took ${runDuration(run.data)}`}
          {run.data.triggered_by && ` · by ${run.data.triggered_by.display_name}`}
        </Text>
        {run.data.source_run_id && (
          <Text size="sm" c="dimmed">
            Posts the selection of a{' '}
            <Anchor component={Link} to={`/projects/${projectId}/runs/${run.data.source_run_id}`} size="sm">
              reviewed dry run
            </Anchor>
            .
          </Text>
        )}
      </div>
      {reviewable && (
        <Text size="sm" c="dimmed">
          Review before posting: untick the commits not to post (they are never posted, by any run), and pick the
          work item of a commit that has none or the wrong one (the link is kept for later runs). Then click Post
          selected.
        </Text>
      )}

      {live && (
        <Alert color="blue" variant="light" title="The run is in progress">
          <Group justify="space-between">
            <Text size="sm">
              {run.data.cancel_requested
                ? 'Cancelling: the run stops after the current commit.'
                : 'This page updates by itself.'}
            </Text>
            {!run.data.cancel_requested && manageable && (
              <Button size="xs" variant="light" color="red" onClick={onCancel} loading={cancel.isPending}>
                Cancel
              </Button>
            )}
          </Group>
        </Alert>
      )}
      {run.data.error_message && (
        <Alert
          color={failed ? 'red' : cancelled ? 'gray' : 'yellow'}
          variant="light"
          title={failed ? 'The run failed' : cancelled ? 'Cancelled' : 'Warnings'}
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
                      {reviewable && <Table.Th aria-label="Selected" w={36} />}
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
                      const shortSha = item.commit_sha.slice(0, 7);
                      const linkable = reviewable && LINKABLE.has(item.action);
                      const picking =
                        linkable &&
                        (item.work_item_id === null || item.action === 'skipped_not_found' || editing === item.id);
                      return (
                        <Table.Tr key={item.id}>
                          {reviewable && (
                            <Table.Td>
                              <Checkbox
                                aria-label={`Post ${shortSha} to #${item.work_item_id ?? '?'}`}
                                checked={item.action === 'would_post'}
                                disabled={item.action !== 'would_post' && item.action !== 'excluded'}
                                onChange={(event) =>
                                  setSelected.mutate(
                                    { itemId: item.id, selected: event.currentTarget.checked },
                                    { onError: showError },
                                  )
                                }
                              />
                            </Table.Td>
                          )}
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
                            <Group gap={6} wrap="nowrap">
                              {item.work_item_id === null ? (
                                !picking && '—'
                              ) : boardConnection ? (
                                <Anchor
                                  href={workItemUrl(boardConnection, item.work_item_id)}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  #{item.work_item_id}
                                </Anchor>
                              ) : (
                                `#${item.work_item_id}`
                              )}
                              {item.manual && (
                                <Badge size="xs" variant="outline" tt="none">
                                  linked
                                </Badge>
                              )}
                              {linkable && !picking && (
                                <Button
                                  size="compact-xs"
                                  variant="subtle"
                                  aria-label={`Change the work item of ${shortSha}`}
                                  onClick={() => setEditing(item.id)}
                                >
                                  Change
                                </Button>
                              )}
                            </Group>
                            {picking && project.data && (
                              <WorkItemPicker
                                projectId={project.data.id}
                                label={`Work item for ${shortSha}`}
                                autoFocus={editing === item.id}
                                onPick={(workItemId) => pick(item, workItemId)}
                              />
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
