import { Alert, Anchor, Badge, Center, Loader, Pagination, Paper, Stack, Table, Text, Title } from '@mantine/core';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { listActivity, type AuditEvent } from '../../api/admin';
import { errorMessage } from '../../api/errors';
import { formatDateTime } from '../../lib/runs';

const PAGE_SIZE = 50;

const TYPE_LABELS: Record<AuditEvent['resource_type'], string> = {
  project: 'Project',
  run: 'Run',
  git_connection: 'Git connection',
  azure_connection: 'Azure connection',
  organization: 'Organization',
};

/** Where an event's resource can be opened, while it still exists. */
function resourceLink(event: AuditEvent): string | null {
  if (!event.resource_id || event.action === 'delete') return null;
  if (event.resource_type === 'project') return `/projects/${event.resource_id}`;
  if (event.resource_type === 'organization') return `/settings/organizations/${event.resource_id}`;
  return null;
}

/** Admins only: what administrators did to other users' data, newest first. */
export function AdminActivityPage() {
  const [page, setPage] = useState(1);
  const activity = useQuery({
    queryKey: ['admin-activity', page],
    queryFn: () => listActivity(page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  });
  const totalPages = activity.data ? Math.max(1, Math.ceil(activity.data.total / PAGE_SIZE)) : 1;

  return (
    <Stack maw={1100}>
      <div>
        <Title order={2}>Activity</Title>
        <Text c="dimmed" size="sm">
          Everything an administrator changed, synced or deleted in other users' projects, connections and
          organizations. Reading isn't recorded; actions that failed leave no entry.
        </Text>
      </div>
      {activity.isPending && (
        <Center p="xl">
          <Loader aria-label="Loading" />
        </Center>
      )}
      {activity.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(activity.error)}
        </Alert>
      )}
      {activity.data && activity.data.items.length === 0 && (
        <Paper withBorder p="xl" radius="md">
          <Text ta="center" c="dimmed">
            No administrator has changed anyone else's data yet.
          </Text>
        </Paper>
      )}
      {activity.data && activity.data.items.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={760}>
            <Table verticalSpacing="sm" aria-label="Activity">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Administrator</Table.Th>
                  <Table.Th>Action</Table.Th>
                  <Table.Th>On</Table.Th>
                  <Table.Th>Owner</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {activity.data.items.map((event) => {
                  const link = resourceLink(event);
                  return (
                    <Table.Tr key={event.id}>
                      <Table.Td>{formatDateTime(event.created_at)}</Table.Td>
                      <Table.Td>{event.actor_email}</Table.Td>
                      <Table.Td>
                        <Badge variant="light" color={event.action === 'delete' ? 'red' : 'blue'}>
                          {event.action}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {TYPE_LABELS[event.resource_type]}
                        </Text>
                        {link ? (
                          <Anchor component={Link} to={link} size="sm">
                            {event.resource_name}
                          </Anchor>
                        ) : (
                          <Text size="sm">{event.resource_name}</Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{event.owner_label}</Text>
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
    </Stack>
  );
}
