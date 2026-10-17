import { Anchor, Button, Drawer, Group, Table, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';

import { deleteErrorMessage } from '../../api/errors';
import type { AzureConnection } from '../../api/types';
import { confirmDelete } from '../../components/confirmDelete';
import { AzureConnectionForm } from '../../components/settings/AzureConnectionForm';
import { SettingsList } from '../../components/settings/SettingsList';
import { TestStatus } from '../../components/TestStatus';
import { useAzureConnections, useDeleteAzureConnection } from '../../hooks/useSettings';

export function AzureConnectionsPage() {
  const query = useAzureConnections();
  const remove = useDeleteAzureConnection();
  const [editing, setEditing] = useState<AzureConnection | 'new' | null>(null);
  // A new key each time the drawer opens; saving keeps the same form (and its test result).
  const [formKey, setFormKey] = useState(0);
  const open = (target: AzureConnection | 'new') => {
    setEditing(target);
    setFormKey((key) => key + 1);
  };

  const onDelete = (connection: AzureConnection) =>
    confirmDelete({
      title: 'Delete Azure connection',
      message: `Delete "${connection.name}"? Its saved PAT is deleted too.`,
      onConfirm: () =>
        remove.mutate(connection.id, {
          onSuccess: () => notifications.show({ color: 'teal', message: `Deleted "${connection.name}".` }),
          onError: (error) => notifications.show({ color: 'red', message: deleteErrorMessage(error) }),
        }),
    });

  return (
    <>
      <SettingsList
        title="Azure connections"
        description="Azure DevOps boards that receive the commit comments."
        query={query}
        addLabel="Add Azure connection"
        onAdd={() => open('new')}
        emptyText="No Azure connections yet. Add the board whose work items should get the comments."
        head={
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Organization</Table.Th>
            <Table.Th>Project</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th aria-label="Actions" />
          </Table.Tr>
        }
        renderRow={(connection) => (
          <Table.Tr key={connection.id}>
            <Table.Td>
              <Anchor component="button" type="button" onClick={() => open(connection)} fw={500}>
                {connection.name}
              </Anchor>
            </Table.Td>
            <Table.Td>
              <Text size="sm" truncate maw={300} title={connection.organization_url}>
                {connection.organization_url}
              </Text>
            </Table.Td>
            <Table.Td>{connection.azure_project}</Table.Td>
            <Table.Td>
              <TestStatus ok={connection.last_test_ok} at={connection.last_test_at} />
            </Table.Td>
            <Table.Td>
              <Group gap="xs" justify="flex-end" wrap="nowrap">
                <Button size="xs" variant="default" onClick={() => open(connection)}>
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
        title={editing === 'new' ? 'New Azure connection' : 'Edit Azure connection'}
      >
        {editing !== null && (
          <AzureConnectionForm
            key={formKey}
            connection={editing === 'new' ? null : editing}
            onSaved={setEditing}
            onClose={() => setEditing(null)}
          />
        )}
      </Drawer>
    </>
  );
}
