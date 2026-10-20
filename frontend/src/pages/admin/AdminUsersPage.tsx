import { Alert, Badge, Button, Center, Group, Loader, Pagination, Paper, Stack, Table, Text, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { listUsers, setUserActive, transferEverything, type AdminUser } from '../../api/admin';
import { errorMessage } from '../../api/errors';
import { TransferModal } from '../../components/TransferModal';
import { useAuth } from '../../hooks/useAuth';
import { formatDateTime } from '../../lib/runs';

const PAGE_SIZE = 50;

/** Admins only: list users and turn accounts on or off. */
export function AdminUsersPage() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [leaving, setLeaving] = useState<AdminUser | null>(null);
  const users = useQuery({
    queryKey: ['admin-users', page],
    queryFn: () => listUsers(page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => setUserActive(id, active),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      notifications.show({
        color: 'teal',
        message: `${user.email} is now ${user.is_active ? 'active' : 'turned off'}.`,
      });
    },
    onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
  });

  const onToggle = (user: AdminUser) => {
    if (user.is_active) {
      // Turning off is the destructive direction: confirm it.
      modals.openConfirmModal({
        title: 'Turn off this account?',
        children: (
          <Text size="sm">
            {user.email} is signed out everywhere and can't log in. Their scheduled syncs stop.
            You can turn the account on again later, or transfer their projects to someone else.
          </Text>
        ),
        labels: { confirm: 'Turn off', cancel: 'Cancel' },
        confirmProps: { color: 'red' },
        onConfirm: () => toggle.mutate({ id: user.id, active: false }),
      });
    } else {
      toggle.mutate({ id: user.id, active: true });
    }
  };

  const totalPages = users.data ? Math.max(1, Math.ceil(users.data.total / PAGE_SIZE)) : 1;

  return (
    <Stack maw={1100}>
      <div>
        <Title order={2}>Users</Title>
        <Text c="dimmed" size="sm">
          Everyone who has an account on this TicketTrail instance.
        </Text>
      </div>
      {users.isPending && (
        <Center p="xl">
          <Loader aria-label="Loading" />
        </Center>
      )}
      {users.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(users.error)}
        </Alert>
      )}
      {users.data && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={720}>
            <Table verticalSpacing="sm" aria-label="Users">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>User</Table.Th>
                  <Table.Th>Role</Table.Th>
                  <Table.Th ta="right">Projects</Table.Th>
                  <Table.Th>Joined</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th aria-label="Actions" />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {users.data.items.map((user) => (
                  <Table.Tr key={user.id}>
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {user.display_name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {user.email}
                      </Text>
                    </Table.Td>
                    <Table.Td>{user.role === 'admin' ? 'Admin' : 'User'}</Table.Td>
                    <Table.Td ta="right">{user.projects}</Table.Td>
                    <Table.Td>{formatDateTime(user.created_at)}</Table.Td>
                    <Table.Td>
                      <Badge color={user.is_active ? 'teal' : 'gray'} variant="light">
                        {user.is_active ? 'Active' : 'Turned off'}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Group gap="xs" justify="flex-end" wrap="nowrap">
                        <Button
                          size="xs"
                          variant="default"
                          onClick={() => setLeaving(user)}
                          aria-label={`Transfer everything ${user.email} owns`}
                        >
                          Transfer all
                        </Button>
                        {user.id !== me?.id && (
                          <Button
                            size="xs"
                            variant={user.is_active ? 'subtle' : 'light'}
                            color={user.is_active ? 'red' : 'teal'}
                            onClick={() => onToggle(user)}
                            aria-label={`${user.is_active ? 'Turn off' : 'Turn on'} ${user.email}`}
                          >
                            {user.is_active ? 'Turn off' : 'Turn on'}
                          </Button>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {totalPages > 1 && <Pagination total={totalPages} value={page} onChange={setPage} />}
      <TransferModal
        opened={leaving !== null}
        onClose={() => setLeaving(null)}
        title={leaving ? `Transfer everything ${leaving.display_name} owns` : 'Transfer'}
        explanation={
          leaving &&
          `Every project and connection of ${leaving.email} goes to the new owner, with the run history and ` +
            'the comments already posted. People they shared projects with keep their access.'
        }
        excludeUserId={leaving?.id ?? ''}
        transfer={(toUserId) => transferEverything(leaving?.id ?? '', toUserId)}
      />
    </Stack>
  );
}
