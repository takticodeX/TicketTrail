import { Alert, Badge, Button, Center, Drawer, Group, Loader, Paper, Stack, Table, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  listAllBoardConnections,
  listAllGitConnections,
  type AdminBoardConnection,
  type AdminGitConnection,
  type ConnectionOwner,
} from '../../api/admin';
import { deleteErrorMessage, errorMessage } from '../../api/errors';
import { confirmDelete } from '../../components/confirmDelete';
import { BoardConnectionForm } from '../../components/settings/BoardConnectionForm';
import { GitConnectionForm } from '../../components/settings/GitConnectionForm';
import { TestStatus } from '../../components/TestStatus';
import { useDeleteBoardConnection, useDeleteGitConnection } from '../../hooks/useSettings';
import { BOARD_LABELS, boardDetail } from '../../lib/boards';

const KEY = ['admin-connections'] as const;

function Owner({ connection }: { connection: ConnectionOwner }) {
  if (connection.organization) {
    return (
      <Text size="sm">
        {connection.organization.name}{' '}
        <Badge size="xs" variant="outline">
          Organization
        </Badge>
      </Text>
    );
  }
  return (
    <>
      <Text size="sm">{connection.owner?.display_name}</Text>
      <Text size="xs" c="dimmed">
        {connection.owner?.email}
      </Text>
    </>
  );
}

/** Admins only: every Git and board connection, editable. Tokens stay write-only. */
export function AdminConnectionsPage() {
  const queryClient = useQueryClient();
  const git = useQuery({ queryKey: [...KEY, 'git'], queryFn: () => listAllGitConnections(1) });
  const boards = useQuery({ queryKey: [...KEY, 'boards'], queryFn: () => listAllBoardConnections(1) });
  const removeGit = useDeleteGitConnection();
  const removeBoard = useDeleteBoardConnection();
  const [gitEditing, setGitEditing] = useState<AdminGitConnection | null>(null);
  const [boardEditing, setBoardEditing] = useState<AdminBoardConnection | null>(null);
  const [formKey, setFormKey] = useState(0);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: KEY });

  const onDelete = (name: string, remove: () => Promise<unknown>) =>
    confirmDelete({
      title: 'Delete connection',
      message: `Delete "${name}"? Its saved token is deleted too. This is recorded.`,
      onConfirm: () =>
        void remove()
          .then(refresh)
          .catch((failure: unknown) => notifications.show({ color: 'red', message: deleteErrorMessage(failure) })),
    });

  const rows = [
    ...(git.data?.items ?? []).map((c) => ({
      connection: c,
      kind: 'Git',
      detail: c.repo_url,
      edit: () => {
        setGitEditing(c);
        setFormKey((key) => key + 1);
      },
      remove: () => removeGit.mutateAsync(c.id),
    })),
    ...(boards.data?.items ?? []).map((c) => ({
      connection: c,
      kind: BOARD_LABELS[c.kind],
      detail: boardDetail(c),
      edit: () => {
        setBoardEditing(c);
        setFormKey((key) => key + 1);
      },
      remove: () => removeBoard.mutateAsync(c.id),
    })),
  ];
  const error = git.error ?? boards.error;

  return (
    <Stack maw={1100}>
      <div>
        <Title order={2}>Connections</Title>
        <Text c="dimmed" size="sm">
          Every Git and board connection on this instance. You can test, change and delete any of them; saved tokens
          are never shown, also to administrators, but you can replace them. Changes are recorded.
        </Text>
      </div>
      {(git.isPending || boards.isPending) && (
        <Center p="xl">
          <Loader aria-label="Loading" />
        </Center>
      )}
      {error && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(error)}
        </Alert>
      )}
      {git.data && boards.data && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          No connections yet.
        </Text>
      )}
      {rows.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={760}>
            <Table verticalSpacing="sm" aria-label="All connections">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Connection</Table.Th>
                  <Table.Th>Owner</Table.Th>
                  <Table.Th ta="right">Projects</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th aria-label="Actions" />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row) => (
                  <Table.Tr key={row.connection.id}>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Badge size="sm" variant="outline">
                          {row.kind}
                        </Badge>
                        <Text size="sm" fw={500}>
                          {row.connection.name}
                        </Text>
                      </Group>
                      <Text size="xs" c="dimmed" truncate maw={380}>
                        {row.detail}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Owner connection={row.connection} />
                    </Table.Td>
                    <Table.Td ta="right">{row.connection.projects}</Table.Td>
                    <Table.Td>
                      <TestStatus ok={row.connection.last_test_ok} at={row.connection.last_test_at} />
                    </Table.Td>
                    <Table.Td>
                      <Group gap="xs" justify="flex-end" wrap="nowrap">
                        <Button
                          size="xs"
                          variant="default"
                          aria-label={`Edit ${row.connection.name}`}
                          onClick={row.edit}
                        >
                          Edit
                        </Button>
                        <Button
                          size="xs"
                          variant="subtle"
                          color="red"
                          aria-label={`Delete ${row.connection.name}`}
                          onClick={() => onDelete(row.connection.name, row.remove)}
                        >
                          Delete
                        </Button>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      <Drawer
        opened={gitEditing !== null}
        onClose={() => setGitEditing(null)}
        position="right"
        size="lg"
        title="Edit Git connection"
      >
        {gitEditing && (
          <GitConnectionForm
            key={formKey}
            connection={gitEditing}
            onSaved={refresh}
            onClose={() => setGitEditing(null)}
          />
        )}
      </Drawer>
      <Drawer
        opened={boardEditing !== null}
        onClose={() => setBoardEditing(null)}
        position="right"
        size="lg"
        title="Edit board connection"
      >
        {boardEditing && (
          <BoardConnectionForm
            key={formKey}
            connection={boardEditing}
            onSaved={refresh}
            onClose={() => setBoardEditing(null)}
          />
        )}
      </Drawer>
    </Stack>
  );
}
