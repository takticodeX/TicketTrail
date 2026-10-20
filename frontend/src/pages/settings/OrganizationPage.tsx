import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Drawer,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { deleteErrorMessage, errorMessage, firstFieldMessage } from '../../api/errors';
import type { AzureConnection, GitConnection, Organization, OrganizationMember, OrganizationRole } from '../../api/types';
import { confirmDelete } from '../../components/confirmDelete';
import { AzureConnectionForm } from '../../components/settings/AzureConnectionForm';
import { GitConnectionForm } from '../../components/settings/GitConnectionForm';
import { TestStatus } from '../../components/TestStatus';
import { useAuth } from '../../hooks/useAuth';
import {
  useAddMember,
  useDeleteOrganization,
  useMembers,
  useOrganization,
  useRemoveMember,
  useUpdateMember,
  useUpdateOrganization,
} from '../../hooks/useOrganizations';
import {
  useAzureConnections,
  useDeleteAzureConnection,
  useDeleteGitConnection,
  useGitConnections,
  useProjects,
} from '../../hooks/useSettings';
import { timeZones } from '../../lib/schedule';

const ROLE_OPTIONS = [
  { value: 'member', label: 'Member' },
  { value: 'admin', label: 'Admin' },
];

function Details({ org }: { org: Organization }) {
  const update = useUpdateOrganization(org.id);
  const [name, setName] = useState(org.name);
  const [timezone, setTimezone] = useState(org.timezone);
  const zones = useMemo(() => timeZones(org.timezone), [org.timezone]);
  const dirty = name.trim() !== org.name || timezone !== org.timezone;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    update.mutate(
      { name: name.trim(), timezone },
      {
        onSuccess: () => notifications.show({ color: 'teal', message: 'Saved.' }),
        onError: (failure) => notifications.show({ color: 'red', message: firstFieldMessage(failure) }),
      },
    );
  };

  return (
    <Paper withBorder radius="md" p="lg" component="form" onSubmit={onSubmit}>
      <Stack>
        <TextInput label="Name" value={name} onChange={(event) => setName(event.currentTarget.value)} />
        <Select
          label="Time zone"
          description="The organization's scheduled syncs run in this time zone."
          searchable
          allowDeselect={false}
          data={zones}
          value={timezone}
          onChange={(value) => setTimezone(value ?? 'UTC')}
        />
        <Group justify="flex-end">
          <Button type="submit" disabled={!dirty} loading={update.isPending}>
            Save
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function Members({ org, isAdmin }: { org: Organization; isAdmin: boolean }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const members = useMembers(org.id);
  const add = useAddMember(org.id);
  const update = useUpdateMember(org.id);
  const remove = useRemoveMember(org.id);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<OrganizationRole>('member');
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
        onSuccess: () => setEmail(''),
        onError: (failure) => setError(firstFieldMessage(failure)),
      },
    );
  };

  const onRemove = (member: OrganizationMember) => {
    const leaving = member.user.id === user?.id;
    modals.openConfirmModal({
      title: leaving ? 'Leave the organization?' : 'Remove this member?',
      children: (
        <Text size="sm">
          {leaving ? 'You lose' : `${member.user.display_name} loses`} access to {org.name}'s projects, including
          any project it shared with {leaving ? 'you' : 'them'}.
        </Text>
      ),
      labels: { confirm: leaving ? 'Leave' : 'Remove', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () =>
        remove.mutate(member.user.id, {
          onSuccess: () => leaving && navigate('/settings/organizations'),
          onError: (failure) => notifications.show({ color: 'red', message: errorMessage(failure) }),
        }),
    });
  };

  return (
    <Stack gap="sm">
      <Title order={4}>Members</Title>
      <Text size="sm" c="dimmed">
        Admins manage members and connections and own every project. Members see every project and can start dry
        runs; share a project with a member to make them its editor.
      </Text>
      {isAdmin && (
        <form onSubmit={onAdd} noValidate>
          <Group align="flex-end" gap="sm">
            <TextInput
              label="Email"
              placeholder="colleague@example.com"
              value={email}
              onChange={(event) => setEmail(event.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Select
              label="Role"
              data={ROLE_OPTIONS}
              value={role}
              allowDeselect={false}
              onChange={(value) => setRole((value as OrganizationRole | null) ?? 'member')}
              w={130}
            />
            <Button type="submit" loading={add.isPending}>
              Add member
            </Button>
          </Group>
        </form>
      )}
      {error && (
        <Alert color="red" variant="light" role="alert">
          {error}
        </Alert>
      )}
      {members.data && (
        <Paper withBorder radius="md">
          <Table verticalSpacing="xs" aria-label="Members">
            <Table.Tbody>
              {members.data.map((member) => (
                <Table.Tr key={member.user.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {member.user.display_name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {member.user.email}
                    </Text>
                  </Table.Td>
                  <Table.Td w={140}>
                    {isAdmin ? (
                      <Select
                        aria-label={`Role of ${member.user.email}`}
                        size="xs"
                        data={ROLE_OPTIONS}
                        value={member.role}
                        allowDeselect={false}
                        onChange={(value) =>
                          value &&
                          value !== member.role &&
                          update.mutate(
                            { userId: member.user.id, role: value as OrganizationRole },
                            { onError: (failure) => notifications.show({ color: 'red', message: errorMessage(failure) }) },
                          )
                        }
                      />
                    ) : (
                      <Text size="sm">{member.role === 'admin' ? 'Admin' : 'Member'}</Text>
                    )}
                  </Table.Td>
                  <Table.Td w={90}>
                    {(isAdmin || member.user.id === user?.id) && (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="red"
                        aria-label={member.user.id === user?.id ? 'Leave the organization' : `Remove ${member.user.email}`}
                        onClick={() => onRemove(member)}
                      >
                        {member.user.id === user?.id ? 'Leave' : 'Remove'}
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
    </Stack>
  );
}

type Editing<T> = T | 'new' | null;

function Connections({ org, isAdmin }: { org: Organization; isAdmin: boolean }) {
  const git = useGitConnections(org.id);
  const azure = useAzureConnections(org.id);
  const removeGit = useDeleteGitConnection();
  const removeAzure = useDeleteAzureConnection();
  const [gitEditing, setGitEditing] = useState<Editing<GitConnection>>(null);
  const [azureEditing, setAzureEditing] = useState<Editing<AzureConnection>>(null);
  // A new key each time a drawer opens; saving keeps the same form (and its test result).
  const [formKey, setFormKey] = useState(0);
  const openGit = (target: GitConnection | 'new') => {
    setGitEditing(target);
    setFormKey((key) => key + 1);
  };
  const openAzure = (target: AzureConnection | 'new') => {
    setAzureEditing(target);
    setFormKey((key) => key + 1);
  };

  const onDelete = (name: string, remove: () => Promise<unknown>) =>
    confirmDelete({
      title: 'Delete connection',
      message: `Delete "${name}"? Its saved token is deleted too.`,
      onConfirm: () =>
        void remove().catch((failure: unknown) =>
          notifications.show({ color: 'red', message: deleteErrorMessage(failure) }),
        ),
    });

  const rows = [
    ...(git.data?.items ?? []).map((c) => ({
      id: c.id,
      kind: 'Git',
      name: c.name,
      detail: c.repo_url,
      ok: c.last_test_ok,
      at: c.last_test_at,
      edit: () => openGit(c),
      remove: () => removeGit.mutateAsync(c.id),
    })),
    ...(azure.data?.items ?? []).map((c) => ({
      id: c.id,
      kind: 'Azure',
      name: c.name,
      detail: `${c.organization_url} · ${c.azure_project}`,
      ok: c.last_test_ok,
      at: c.last_test_at,
      edit: () => openAzure(c),
      remove: () => removeAzure.mutateAsync(c.id),
    })),
  ];

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={4}>Connections</Title>
        {isAdmin && (
          <Group gap="xs">
            <Button size="xs" variant="default" onClick={() => openGit('new')}>
              Add Git connection
            </Button>
            <Button size="xs" variant="default" onClick={() => openAzure('new')}>
              Add Azure connection
            </Button>
          </Group>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        Every member can use these in the organization's projects. Tokens are never shown; only admins change them.
      </Text>
      {rows.length === 0 ? (
        <Text size="sm" c="dimmed">
          No connections yet.
        </Text>
      ) : (
        <Paper withBorder radius="md">
          <Table verticalSpacing="xs" aria-label="Organization connections">
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.id}>
                  <Table.Td w={70}>
                    <Badge size="sm" variant="outline">
                      {row.kind}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {row.name}
                    </Text>
                    <Text size="xs" c="dimmed" truncate maw={420}>
                      {row.detail}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <TestStatus ok={row.ok} at={row.at} />
                  </Table.Td>
                  <Table.Td>
                    {isAdmin && (
                      <Group gap="xs" justify="flex-end" wrap="nowrap">
                        <Button size="xs" variant="default" onClick={row.edit}>
                          Edit
                        </Button>
                        <Button size="xs" variant="subtle" color="red" onClick={() => onDelete(row.name, row.remove)}>
                          Delete
                        </Button>
                      </Group>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      <Drawer
        opened={gitEditing !== null}
        onClose={() => setGitEditing(null)}
        position="right"
        size="lg"
        title={gitEditing === 'new' ? `New Git connection for ${org.name}` : 'Edit Git connection'}
      >
        {gitEditing !== null && (
          <GitConnectionForm
            key={formKey}
            connection={gitEditing === 'new' ? null : gitEditing}
            organizationId={org.id}
            onSaved={setGitEditing}
            onClose={() => setGitEditing(null)}
          />
        )}
      </Drawer>
      <Drawer
        opened={azureEditing !== null}
        onClose={() => setAzureEditing(null)}
        position="right"
        size="lg"
        title={azureEditing === 'new' ? `New Azure connection for ${org.name}` : 'Edit Azure connection'}
      >
        {azureEditing !== null && (
          <AzureConnectionForm
            key={formKey}
            connection={azureEditing === 'new' ? null : azureEditing}
            organizationId={org.id}
            onSaved={setAzureEditing}
            onClose={() => setAzureEditing(null)}
          />
        )}
      </Drawer>
    </Stack>
  );
}

function Projects({ org }: { org: Organization }) {
  const projects = useProjects();
  const mine = (projects.data?.items ?? []).filter((p) => p.organization?.id === org.id);
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={4}>Projects</Title>
        <Button size="xs" component={Link} to={`/settings/projects/new?organization=${org.id}`}>
          New project
        </Button>
      </Group>
      {mine.length === 0 ? (
        <Text size="sm" c="dimmed">
          No projects yet. Create one, or move one of yours here from its page.
        </Text>
      ) : (
        <Stack gap={4}>
          {mine.map((p) => (
            <Anchor key={p.id} component={Link} to={`/projects/${p.id}`} size="sm">
              {p.name}
            </Anchor>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export function OrganizationPage() {
  const { organizationId = '' } = useParams();
  const navigate = useNavigate();
  const org = useOrganization(organizationId);
  const remove = useDeleteOrganization();

  if (org.isPending) {
    return (
      <Center p="xl">
        <Loader aria-label="Loading" />
      </Center>
    );
  }
  if (org.isError) {
    return (
      <Alert color="red" variant="light" role="alert">
        {errorMessage(org.error)}
      </Alert>
    );
  }
  const isAdmin = org.data.role === 'admin';

  const onDelete = () =>
    confirmDelete({
      title: 'Delete organization',
      message: `Delete "${org.data.name}"? It must own no projects and no connections.`,
      onConfirm: () =>
        remove.mutate(org.data.id, {
          onSuccess: () => navigate('/settings/organizations'),
          onError: (failure) => notifications.show({ color: 'red', message: errorMessage(failure) }),
        }),
    });

  return (
    <Stack maw={1100}>
      <div>
        <Anchor component={Link} to="/settings/organizations" size="sm">
          ← Organizations
        </Anchor>
        <Group justify="space-between">
          <Group gap="xs">
            <Title order={2}>{org.data.name}</Title>
            <Badge variant="light" color={isAdmin ? 'blue' : 'gray'}>
              {isAdmin ? 'Admin' : 'Member'}
            </Badge>
          </Group>
          {isAdmin && (
            <Button variant="subtle" color="red" onClick={onDelete}>
              Delete organization
            </Button>
          )}
        </Group>
        <Text size="sm" c="dimmed">
          Schedules run in {org.data.timezone}.
        </Text>
      </div>
      {isAdmin && <Details key={`${org.data.name}|${org.data.timezone}`} org={org.data} />}
      <Members org={org.data} isAdmin={isAdmin} />
      <Connections org={org.data} isAdmin={isAdmin} />
      <Projects org={org.data} />
    </Stack>
  );
}
