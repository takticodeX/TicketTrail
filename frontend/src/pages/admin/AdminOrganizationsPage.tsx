import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Pagination,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { listAllOrganizations, promoteAdmin, type AdminOrganization } from '../../api/admin';
import { errorMessage, firstFieldMessage } from '../../api/errors';

const PAGE_SIZE = 50;

function PromoteModal({ organization, onClose }: { organization: AdminOrganization | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const promote = useMutation({
    mutationFn: (id: string) => promoteAdmin(organization?.id ?? '', id),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ['admin-organizations'] });
      notifications.show({ color: 'teal', message: `${updated.name} has a new admin.` });
      close();
    },
    onError: (failure) => setError(firstFieldMessage(failure)),
  });
  const close = () => {
    setUserId(null);
    setError(null);
    onClose();
  };
  const options = (organization?.people ?? [])
    .filter((p) => p.role === 'member')
    .map((p) => ({ value: p.user.id, label: `${p.user.display_name} (${p.user.email})` }));

  return (
    <Modal opened={organization !== null} onClose={close} title={`Make an admin of ${organization?.name ?? ''}`}>
      <Stack>
        <Text size="sm">
          The member gets the owner role on every project of the organization and manages its members and
          connections.
        </Text>
        <Select
          label="Member"
          placeholder="Pick a member"
          data={options}
          value={userId}
          onChange={setUserId}
          searchable
          nothingFoundMessage="Every member is already an admin"
        />
        {error && (
          <Alert color="red" variant="light" role="alert">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={close}>
            Cancel
          </Button>
          <Button disabled={!userId} loading={promote.isPending} onClick={() => userId && promote.mutate(userId)}>
            Make admin
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Admins only: every organization and its admins, to rescue one left without an admin. */
export function AdminOrganizationsPage() {
  const [page, setPage] = useState(1);
  const [promoting, setPromoting] = useState<AdminOrganization | null>(null);
  const organizations = useQuery({
    queryKey: ['admin-organizations', page],
    queryFn: () => listAllOrganizations(page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  });
  const totalPages = organizations.data ? Math.max(1, Math.ceil(organizations.data.total / PAGE_SIZE)) : 1;

  return (
    <Stack maw={1100}>
      <div>
        <Title order={2}>Organizations</Title>
        <Text c="dimmed" size="sm">
          Every organization on this instance. Open one to manage it as its admin, or make a member an admin when
          an organization has none left.
        </Text>
      </div>
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
      {organizations.data && organizations.data.items.length === 0 && (
        <Text size="sm" c="dimmed">
          No organizations yet.
        </Text>
      )}
      {organizations.data && organizations.data.items.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={720}>
            <Table verticalSpacing="sm" aria-label="All organizations">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Organization</Table.Th>
                  <Table.Th>Admins</Table.Th>
                  <Table.Th ta="right">Members</Table.Th>
                  <Table.Th ta="right">Projects</Table.Th>
                  <Table.Th aria-label="Actions" />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {organizations.data.items.map((org) => (
                  <Table.Tr key={org.id}>
                    <Table.Td>
                      <Anchor component={Link} to={`/settings/organizations/${org.id}`} size="sm" fw={500}>
                        {org.name}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>
                      {org.admins.length > 0 ? (
                        <Text size="sm">{org.admins.map((a) => a.email).join(', ')}</Text>
                      ) : (
                        <Badge color="red" variant="light">
                          No admin
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td ta="right">{org.members}</Table.Td>
                    <Table.Td ta="right">{org.projects}</Table.Td>
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="default"
                        aria-label={`Make an admin of ${org.name}`}
                        disabled={!org.people.some((p) => p.role === 'member')}
                        onClick={() => setPromoting(org)}
                      >
                        Make admin
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {totalPages > 1 && <Pagination total={totalPages} value={page} onChange={setPage} />}
      <PromoteModal organization={promoting} onClose={() => setPromoting(null)} />
    </Stack>
  );
}
