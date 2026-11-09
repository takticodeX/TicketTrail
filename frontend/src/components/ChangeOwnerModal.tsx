import { Alert, Button, Group, Modal, SegmentedControl, Select, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { listAllOrganizations, listUsers } from '../api/admin';
import { firstFieldMessage } from '../api/errors';
import type { OrganizationSummary, UserSummary } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { useChangeOwner, useMembers, useOrganizations } from '../hooks/useOrganizations';

type Target = 'organization' | 'user';

/**
 * "Change owner": give a project, with its connections, to an organization or a user.
 *
 * - Into an organization you belong to (administrators: any organization).
 * - To a member of the project's organization (administrators: any active user).
 */
export function ChangeOwnerModal({
  project,
  opened,
  onClose,
}: {
  project: { id: string; name: string; owner: UserSummary | null; organization: OrganizationSummary | null };
  opened: boolean;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.role === 'admin';
  const change = useChangeOwner(project.id);
  const mine = useOrganizations();
  const everyOrganization = useQuery({
    queryKey: ['admin-organizations', 'all'],
    queryFn: () => listAllOrganizations(1, 100),
    enabled: opened && isAdmin,
  });
  const everyUser = useQuery({
    queryKey: ['admin-users', 'recipients'],
    queryFn: () => listUsers(1, 100),
    enabled: opened && isAdmin,
  });
  const members = useMembers(opened && !isAdmin && project.organization ? project.organization.id : undefined);

  const organizations = (isAdmin ? everyOrganization.data?.items : mine.data) ?? [];
  const organizationOptions = organizations
    .filter((org) => org.id !== project.organization?.id)
    .map((org) => ({ value: org.id, label: org.name }));
  const people: UserSummary[] = isAdmin
    ? (everyUser.data?.items ?? []).filter((u) => u.is_active)
    : (members.data ?? []).map((m) => m.user);
  const userOptions = people
    .filter((u) => u.id !== project.owner?.id)
    .map((u) => ({ value: u.id, label: `${u.display_name} (${u.email})` }));
  const canGiveToUser = isAdmin || project.organization !== null;

  const [kind, setKind] = useState<Target>(project.organization ? 'user' : 'organization');
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setTarget(null);
    setError(null);
    onClose();
  };

  const onConfirm = () => {
    if (!target) return;
    setError(null);
    change.mutate(kind === 'organization' ? { organization_id: target } : { to_user_id: target }, {
      onSuccess: (done) => {
        notifications.show({ color: 'teal', message: done.summary });
        close();
        // Whoever gives a project to someone else may lose access to it.
        if (kind === 'user' && target !== user?.id && !isAdmin) navigate('/');
      },
      onError: (failure) => setError(firstFieldMessage(failure)),
    });
  };

  return (
    <Modal opened={opened} onClose={close} title={`Change the owner of "${project.name}"`}>
      <Stack>
        {canGiveToUser && (
          <SegmentedControl
            value={kind}
            onChange={(value) => {
              setKind(value as Target);
              setTarget(null);
            }}
            data={[
              { value: 'organization', label: 'An organization' },
              { value: 'user', label: 'A user' },
            ]}
          />
        )}
        <Select
          label={kind === 'organization' ? 'Organization' : 'User'}
          placeholder={kind === 'organization' ? 'Pick an organization' : 'Pick a user'}
          data={kind === 'organization' ? organizationOptions : userOptions}
          value={target}
          onChange={setTarget}
          searchable
          nothingFoundMessage={kind === 'organization' ? 'You are not in any other organization' : 'Nobody to pick'}
        />
        <Text size="xs" c="dimmed">
          The connections come along, still encrypted; one the current owner uses in another project is copied. A
          personal owner who isn't an admin of the receiving organization stays an editor. The change is recorded.
        </Text>
        {error && (
          <Alert color="red" variant="light" role="alert">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={close}>
            Cancel
          </Button>
          <Button disabled={!target} loading={change.isPending} onClick={onConfirm}>
            Change owner
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
