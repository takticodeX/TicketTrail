import { Alert, Anchor, Badge, Button, Center, Group, Loader, Modal, Paper, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { errorMessage, firstFieldMessage } from '../../api/errors';
import { useCreateOrganization, useOrganizations } from '../../hooks/useOrganizations';

function NewOrganizationModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const create = useCreateOrganization();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError('Enter a name.');
      return;
    }
    create.mutate(
      { name: name.trim() },
      {
        onSuccess: (org) => {
          notifications.show({ color: 'teal', message: `Created "${org.name}".` });
          setName('');
          onClose();
          navigate(`/settings/organizations/${org.id}`);
        },
        onError: (failure) => setError(firstFieldMessage(failure)),
      },
    );
  };

  return (
    <Modal opened={opened} onClose={onClose} title="New organization">
      <form onSubmit={onSubmit} noValidate>
        <Stack>
          <TextInput label="Name" value={name} onChange={(event) => setName(event.currentTarget.value)} data-autofocus />
          <Text size="xs" c="dimmed">
            You become its admin. Its schedules run in your time zone until you change it.
          </Text>
          {error && (
            <Alert color="red" variant="light" role="alert">
              {error}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="subtle" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

/** The organizations you belong to. Anyone can create one. */
export function OrganizationsPage() {
  const organizations = useOrganizations();
  const [creating, setCreating] = useState(false);

  return (
    <Stack maw={1100}>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Organizations</Title>
          <Text c="dimmed" size="sm">
            Teams that own projects and connections together, so nothing is lost when someone leaves.
          </Text>
        </div>
        <Button onClick={() => setCreating(true)}>New organization</Button>
      </Group>
      {organizations.isPending && (
        <Center p="xl">
          <Loader aria-label="Loading" />
        </Center>
      )}
      {organizations.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(organizations.error)}
        </Alert>
      )}
      {organizations.data && organizations.data.length === 0 && (
        <Paper withBorder p="xl" radius="md">
          <Text ta="center" c="dimmed">
            You're not in any organization yet. Create one, or ask an admin of yours to add you.
          </Text>
        </Paper>
      )}
      {organizations.data && organizations.data.length > 0 && (
        <Paper withBorder radius="md">
          <Table verticalSpacing="sm" aria-label="Organizations">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Your role</Table.Th>
                <Table.Th ta="right">Members</Table.Th>
                <Table.Th ta="right">Projects</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {organizations.data.map((org) => (
                <Table.Tr key={org.id}>
                  <Table.Td>
                    <Anchor component={Link} to={`/settings/organizations/${org.id}`} fw={500}>
                      {org.name}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" color={org.role === 'admin' ? 'blue' : 'gray'}>
                      {org.role === 'admin' ? 'Admin' : 'Member'}
                    </Badge>
                  </Table.Td>
                  <Table.Td ta="right">{org.members}</Table.Td>
                  <Table.Td ta="right">{org.projects}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      <NewOrganizationModal opened={creating} onClose={() => setCreating(false)} />
    </Stack>
  );
}
