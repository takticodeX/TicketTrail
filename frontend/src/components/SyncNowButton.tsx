import { Button, Group, Stack, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import { getRun } from '../api/runs';
import type { Project, SyncRun, SyncRunDetail } from '../api/types';
import { runKeys, useStartSync } from '../hooks/useRuns';
import { formatDateTime } from '../lib/runs';

function lastDryRun(runs: SyncRun[] | undefined): SyncRun | undefined {
  return runs?.find((run) => run.dry_run && (run.status === 'success' || run.status === 'partial'));
}

function Summary({ project, dryRun }: { project: Project; dryRun: SyncRunDetail | null }) {
  if (dryRun) {
    const toPost = dryRun.counts_by_action.would_post ?? 0;
    const missing = dryRun.counts_by_action.skipped_not_found ?? 0;
    return (
      <Stack gap="xs">
        <Text size="sm">
          The last dry run ({formatDateTime(dryRun.started_at ?? dryRun.created_at)}) found{' '}
          <strong>
            {toPost} {toPost === 1 ? 'comment' : 'comments'}
          </strong>{' '}
          to post.
        </Text>
        {missing > 0 && (
          <Text size="sm">
            {missing} {missing === 1 ? 'reference points' : 'references point'} to work items that don't
            exist; they will be skipped.
          </Text>
        )}
        <Text size="sm" c="dimmed">
          Commits pushed since that dry run are included too. Nothing is ever posted twice.
        </Text>
      </Stack>
    );
  }
  const scope = project.start_from
    ? `every commit with a work item reference since ${project.start_from}`
    : 'every commit with a work item reference in the whole history';
  return (
    <Stack gap="xs">
      <Text size="sm">
        <strong>There is no dry run yet.</strong> A sync now posts a comment for {scope}.
      </Text>
      <Text size="sm" c="dimmed">
        Run a dry run first to see exactly what would be posted.
      </Text>
    </Stack>
  );
}

/** "Sync now" posts to Azure DevOps, so it asks first, with the last dry run's numbers. */
export function SyncNowButton({
  project,
  runs,
  onDryRun,
}: {
  project: Project;
  runs: SyncRun[] | undefined;
  onDryRun: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const startSync = useStartSync(project.id);
  const [preparing, setPreparing] = useState(false);

  const sync = () =>
    startSync.mutate(false, {
      onSuccess: ({ run_id }) => navigate(`/projects/${project.id}/runs/${run_id}`),
      onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
    });

  const onClick = async () => {
    const latest = lastDryRun(runs);
    let detail: SyncRunDetail | null = null;
    if (latest) {
      setPreparing(true);
      try {
        detail = await queryClient.fetchQuery({
          queryKey: runKeys.detail(latest.id),
          queryFn: () => getRun(latest.id),
        });
      } catch {
        detail = null;
      } finally {
        setPreparing(false);
      }
    }
    const id = modals.open({
      title: 'Post comments to Azure DevOps?',
      children: (
        <Stack>
          <Summary project={project} dryRun={detail} />
          <Group justify="flex-end" gap="sm">
            <Button variant="subtle" onClick={() => modals.close(id)}>
              Cancel
            </Button>
            {!detail && (
              <Button
                variant="default"
                onClick={() => {
                  modals.close(id);
                  onDryRun();
                }}
              >
                Dry run first
              </Button>
            )}
            <Button
              onClick={() => {
                modals.close(id);
                sync();
              }}
            >
              {detail ? 'Post comments' : 'Sync anyway'}
            </Button>
          </Group>
        </Stack>
      ),
    });
  };

  return (
    <Button onClick={() => void onClick()} loading={preparing || startSync.isPending}>
      Sync now
    </Button>
  );
}
