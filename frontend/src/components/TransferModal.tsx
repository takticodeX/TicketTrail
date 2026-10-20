import { Alert, Button, Group, Modal, Select, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { listUsers, type OwnershipTransfer } from '../api/admin';
import { errorMessage, firstFieldMessage } from '../api/errors';

/**
 * Pick who receives a project (or everything a user owns), then transfer.
 * Secrets move still encrypted; connections the previous owner still uses are copied.
 */
export function TransferModal({
  opened,
  onClose,
  title,
  explanation,
  excludeUserId,
  transfer,
}: {
  opened: boolean;
  onClose: () => void;
  title: string;
  explanation: ReactNode;
  /** The current owner: they can't receive their own projects. */
  excludeUserId: string;
  transfer: (toUserId: string) => Promise<OwnershipTransfer>;
}) {
  const queryClient = useQueryClient();
  const [to, setTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const users = useQuery({
    queryKey: ['admin-users', 'recipients'],
    queryFn: () => listUsers(1, 100),
    enabled: opened,
  });
  const run = useMutation({
    mutationFn: transfer,
    onSuccess: (done) => {
      for (const key of ['admin-users', 'admin-projects', 'admin-transfers', 'projects']) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
      notifications.show({ color: 'teal', message: done.summary });
      close();
    },
    onError: (failure) => setError(firstFieldMessage(failure)),
  });

  const close = () => {
    setTo(null);
    setError(null);
    onClose();
  };

  const options = (users.data?.items ?? [])
    .filter((u) => u.is_active && u.id !== excludeUserId)
    .map((u) => ({ value: u.id, label: `${u.display_name} (${u.email})` }));

  return (
    <Modal opened={opened} onClose={close} title={title}>
      <Stack>
        <Text size="sm">{explanation}</Text>
        <Select
          label="New owner"
          placeholder={users.isPending ? 'Loading users…' : 'Pick a user'}
          data={options}
          value={to}
          onChange={setTo}
          searchable
          nothingFoundMessage="No other active user"
        />
        <Text size="xs" c="dimmed">
          Saved tokens move still encrypted: nobody sees them. The transfer is recorded.
        </Text>
        {users.isError && (
          <Alert color="red" variant="light" role="alert">
            {errorMessage(users.error)}
          </Alert>
        )}
        {error && (
          <Alert color="red" variant="light" role="alert">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={close}>
            Cancel
          </Button>
          <Button
            disabled={!to}
            loading={run.isPending}
            onClick={() => {
              setError(null);
              if (to) run.mutate(to);
            }}
          >
            Transfer
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
