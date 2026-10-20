import { Alert, Button, Center, Drawer, Group, Loader, Select, Stack, Table, Text, TextInput } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useState, type FormEvent } from 'react';

import { errorMessage, firstFieldMessage } from '../api/errors';
import type { Project, ProjectShare, ShareRole } from '../api/types';
import { useMembers } from '../hooks/useOrganizations';
import { useAddShare, useRemoveShare, useShares, useUpdateShare } from '../hooks/useSharing';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '../lib/access';

const ROLE_OPTIONS = (['viewer', 'editor'] as const).map((role) => ({ value: role, label: ROLE_LABELS[role] }));

/** The owner shares a project with registered users, by their exact email. */
export function ShareDrawer({ project, opened, onClose }: { project: Project; opened: boolean; onClose: () => void }) {
  const shares = useShares(project.id, opened);
  const add = useAddShare(project.id);
  const update = useUpdateShare(project.id);
  const remove = useRemoveShare(project.id);
  // An organization's members see each other: offer them by name.
  const members = useMembers(opened && project.organization ? project.organization.id : undefined);
  const memberOptions = (members.data ?? [])
    .filter((m) => m.role === 'member')
    .map((m) => ({ value: m.user.email, label: `${m.user.display_name} (${m.user.email})` }));
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<ShareRole>('viewer');
  const [error, setError] = useState<string | null>(null);

  const onAdd = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError('Enter the email of a TicketTrail user.');
      return;
    }
    add.mutate(
      { email: email.trim(), role },
      {
        onSuccess: (share) => {
          setEmail('');
          notifications.show({
            color: 'teal',
            message: `Shared with ${share.user.display_name} as ${ROLE_LABELS[share.role].toLowerCase()}.`,
          });
        },
        onError: (failure) => setError(firstFieldMessage(failure)),
      },
    );
  };

  const onRoleChange = (share: ProjectShare, value: string | null) => {
    if (!value || value === share.role) return;
    update.mutate(
      { userId: share.user.id, role: value as ShareRole },
      { onError: (failure) => notifications.show({ color: 'red', message: errorMessage(failure) }) },
    );
  };

  const onRemove = (share: ProjectShare) =>
    modals.openConfirmModal({
      title: 'Stop sharing?',
      children: (
        <Text size="sm">
          {share.user.display_name} ({share.user.email}) loses access to "{project.name}" and its runs.
        </Text>
      ),
      labels: { confirm: 'Stop sharing', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () =>
        remove.mutate(share.user.id, {
          onError: (failure) => notifications.show({ color: 'red', message: errorMessage(failure) }),
        }),
    });

  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="lg" title={`Share "${project.name}"`}>
      <Stack>
        <form onSubmit={onAdd} noValidate>
          <Stack gap="sm">
            {memberOptions.length > 0 && (
              <Select
                label={`Member of ${project.organization?.name ?? 'the organization'}`}
                description="Members are viewers of every project; make one an editor of this one."
                placeholder="Pick a member"
                data={memberOptions}
                value={memberOptions.some((o) => o.value === email) ? email : null}
                onChange={(value) => {
                  setEmail(value ?? '');
                  if (value) setRole('editor');
                }}
                searchable
                clearable
              />
            )}
            <Group align="flex-start" gap="sm" wrap="nowrap">
              <TextInput
                label="Email"
                placeholder="colleague@example.com"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.currentTarget.value)}
                style={{ flex: 1 }}
              />
              <Select
                label="Role"
                data={ROLE_OPTIONS}
                value={role}
                onChange={(value) => setRole((value as ShareRole | null) ?? 'viewer')}
                allowDeselect={false}
                w={130}
              />
            </Group>
            <Text size="xs" c="dimmed">
              The {ROLE_LABELS[role].toLowerCase()} {ROLE_DESCRIPTIONS[role]} Only you can share, change the
              connections or delete the project. Your tokens are never shown.
            </Text>
            {error && (
              <Alert color="red" variant="light" role="alert">
                {error}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button type="submit" loading={add.isPending}>
                Share
              </Button>
            </Group>
          </Stack>
        </form>

        {shares.isPending && (
          <Center p="md">
            <Loader size="sm" aria-label="Loading" />
          </Center>
        )}
        {shares.isError && (
          <Alert color="red" variant="light" role="alert">
            {errorMessage(shares.error)}
          </Alert>
        )}
        {shares.data && shares.data.length === 0 && (
          <Text size="sm" c="dimmed">
            Not shared with anyone yet.
          </Text>
        )}
        {shares.data && shares.data.length > 0 && (
          <Table verticalSpacing="xs" aria-label="Shared with">
            <Table.Tbody>
              {shares.data.map((share) => (
                <Table.Tr key={share.user.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {share.user.display_name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {share.user.email}
                    </Text>
                  </Table.Td>
                  <Table.Td w={130}>
                    <Select
                      aria-label={`Role of ${share.user.email}`}
                      size="xs"
                      data={ROLE_OPTIONS}
                      value={share.role}
                      allowDeselect={false}
                      onChange={(value) => onRoleChange(share, value)}
                    />
                  </Table.Td>
                  <Table.Td w={80}>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="red"
                      aria-label={`Stop sharing with ${share.user.email}`}
                      onClick={() => onRemove(share)}
                    >
                      Remove
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Drawer>
  );
}
