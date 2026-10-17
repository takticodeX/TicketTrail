import { Anchor, Button, Drawer, Group, Table, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';

import { deleteErrorMessage } from '../../api/errors';
import type { GitConnection } from '../../api/types';
import { confirmDelete } from '../../components/confirmDelete';
import { GitConnectionForm } from '../../components/settings/GitConnectionForm';
import { SettingsList } from '../../components/settings/SettingsList';
import { TestStatus } from '../../components/TestStatus';
import { useDeleteGitConnection, useGitConnections } from '../../hooks/useSettings';
import { HOST_LABELS } from '../../lib/gitHosts';

const AUTH_LABELS = { token: 'Token', basic: 'Password', none: 'Public' } as const;

export function GitConnectionsPage() {
  const query = useGitConnections();
  const remove = useDeleteGitConnection();
  const [editing, setEditing] = useState<GitConnection | 'new' | null>(null);

  const onDelete = (connection: GitConnection) =>
    confirmDelete({
      title: 'Delete Git connection',
      message: `Delete "${connection.name}"? Its saved token is deleted too.`,
      onConfirm: () =>
        remove.mutate(connection.id, {
          onSuccess: () => notifications.show({ color: 'teal', message: `Deleted "${connection.name}".` }),
          onError: (error) => notifications.show({ color: 'red', message: deleteErrorMessage(error) }),
        }),
    });

  return (
    <>
      <SettingsList
        title="Git connections"
        description="Repositories TicketTrail reads commits from, over HTTPS."
        query={query}
        addLabel="Add Git connection"
        onAdd={() => setEditing('new')}
        emptyText="No Git connections yet. Add the repository whose commits should be posted."
        head={
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Repository</Table.Th>
            <Table.Th>Auth</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th aria-label="Actions" />
          </Table.Tr>
        }
        renderRow={(connection) => (
          <Table.Tr key={connection.id}>
            <Table.Td>
              <Anchor component="button" type="button" onClick={() => setEditing(connection)} fw={500}>
                {connection.name}
              </Anchor>
            </Table.Td>
            <Table.Td>
              <Text size="sm" truncate maw={340} title={connection.repo_url}>
                {connection.repo_url}
              </Text>
              <Text size="xs" c="dimmed">
                {HOST_LABELS[connection.host]}
              </Text>
            </Table.Td>
            <Table.Td>{AUTH_LABELS[connection.auth_type]}</Table.Td>
            <Table.Td>
              <TestStatus ok={connection.last_test_ok} at={connection.last_test_at} />
            </Table.Td>
            <Table.Td>
              <Group gap="xs" justify="flex-end" wrap="nowrap">
                <Button size="xs" variant="default" onClick={() => setEditing(connection)}>
                  Edit
                </Button>
                <Button size="xs" variant="subtle" color="red" onClick={() => onDelete(connection)}>
                  Delete
                </Button>
              </Group>
            </Table.Td>
          </Table.Tr>
        )}
      />
      <Drawer
        opened={editing !== null}
        onClose={() => setEditing(null)}
        position="right"
        size="lg"
        title={editing === 'new' ? 'New Git connection' : 'Edit Git connection'}
      >
        {editing !== null && (
          <GitConnectionForm
            key={editing === 'new' ? 'new' : editing.id}
            connection={editing === 'new' ? null : editing}
            onSaved={setEditing}
            onClose={() => setEditing(null)}
          />
        )}
      </Drawer>
    </>
  );
}
