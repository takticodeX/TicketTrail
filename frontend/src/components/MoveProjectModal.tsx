import { Alert, Button, Group, Modal, Select, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { firstFieldMessage } from '../api/errors';
import type { Project } from '../api/types';
import { useAuth } from '../hooks/useAuth';
import { useMembers, useMoveProject, useOrganizations } from '../hooks/useOrganizations';

/**
 * A personal project moves into one of the owner's organizations; an organization's
 * project moves out to one of its members (its admins only).
 */
export function MoveProjectModal({ project, opened, onClose }: { project: Project; opened: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const organization = project.organization;
  const organizations = useOrganizations();
  const members = useMembers(opened && organization ? organization.id : undefined);
  const move = useMoveProject(project.id);
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const options = organization
    ? (members.data ?? []).map((m) => ({ value: m.user.id, label: `${m.user.display_name} (${m.user.email})` }))
    : (organizations.data ?? []).map((org) => ({ value: org.id, label: org.name }));

  const close = () => {
    setTarget(null);
    setError(null);
    onClose();
  };

  const onMove = () => {
    if (!target) return;
    setError(null);
    move.mutate(organization ? { to_user_id: target } : { organization_id: target }, {
      onSuccess: (done) => {
        notifications.show({ color: 'teal', message: done.summary });
        close();
        // An admin who moved it to someone else no longer sees it.
        if (organization && target !== user?.id) navigate('/');
      },
      onError: (failure) => setError(firstFieldMessage(failure)),
    });
  };

  return (
    <Modal opened={opened} onClose={close} title={organization ? 'Move to a member' : 'Move to an organization'}>
      <Stack>
        <Text size="sm">
          {organization
            ? `The member becomes the owner of "${project.name}", with its connections. ` +
              `A connection ${organization.name} still uses in another project is copied.`
            : `"${project.name}" and its connections go to the organization: its admins own it and every member ` +
              'sees it. You stay its editor. A connection you still use in another project is copied.'}
        </Text>
        <Select
          label={organization ? 'Member' : 'Organization'}
          placeholder={organization ? 'Pick a member' : 'Pick an organization'}
          data={options}
          value={target}
          onChange={setTarget}
          searchable
          nothingFoundMessage={organization ? 'No members' : 'You are not in any organization'}
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
          <Button disabled={!target} loading={move.isPending} onClick={onMove}>
            Move
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
