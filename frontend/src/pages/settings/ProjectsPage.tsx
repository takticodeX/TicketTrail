import { Anchor, Badge, Button, Group, Table, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Link, useNavigate } from 'react-router-dom';

import { errorMessage } from '../../api/errors';
import type { Project } from '../../api/types';
import { confirmDelete } from '../../components/confirmDelete';
import { SettingsList } from '../../components/settings/SettingsList';
import {
  useAzureConnections,
  useDeleteProject,
  useGitConnections,
  useProjects,
} from '../../hooks/useSettings';
import { describeCron } from '../../lib/schedule';

function scheduleLabel(project: Project): string {
  if (!project.schedule_enabled || !project.schedule_cron) return 'Manual only';
  try {
    return describeCron(project.schedule_cron);
  } catch {
    return project.schedule_cron;
  }
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const query = useProjects();
  const git = useGitConnections();
  const azure = useAzureConnections();
  const remove = useDeleteProject();

  const gitName = (id: string) => git.data?.items.find((c) => c.id === id)?.name ?? '…';
  const azureName = (id: string) => azure.data?.items.find((c) => c.id === id)?.name ?? '…';

  const onDelete = (project: Project) =>
    confirmDelete({
      title: 'Delete project',
      message: `Delete "${project.name}"? Its connections are kept.`,
      onConfirm: () =>
        remove.mutate(project.id, {
          onSuccess: () => notifications.show({ color: 'teal', message: `Deleted "${project.name}".` }),
          onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
        }),
    });

  return (
    <SettingsList
      title="Projects"
      description="Each project pairs one Git repository with one Azure DevOps board."
      query={query}
      addLabel="New project"
      onAdd={() => navigate('/settings/projects/new')}
      emptyText="No projects yet. Create one to start posting commit messages to work items."
      head={
        <Table.Tr>
          <Table.Th>Name</Table.Th>
          <Table.Th>Repository</Table.Th>
          <Table.Th>Board</Table.Th>
          <Table.Th>Schedule</Table.Th>
          <Table.Th aria-label="Actions" />
        </Table.Tr>
      }
      renderRow={(project) => (
        <Table.Tr key={project.id}>
          <Table.Td>
            <Anchor component={Link} to={`/settings/projects/${project.id}`} fw={500}>
              {project.name}
            </Anchor>
            {project.dry_run_default && (
              <Badge ml="xs" size="xs" variant="light" color="yellow">
                Dry run
              </Badge>
            )}
          </Table.Td>
          <Table.Td>
            <Text size="sm">{gitName(project.git_connection_id)}</Text>
            <Text size="xs" c="dimmed">
              {project.branches.length > 0 ? project.branches.join(', ') : 'Default branch'}
            </Text>
          </Table.Td>
          <Table.Td>{azureName(project.azure_connection_id)}</Table.Td>
          <Table.Td>
            <Text size="sm">{scheduleLabel(project)}</Text>
          </Table.Td>
          <Table.Td>
            <Group gap="xs" justify="flex-end" wrap="nowrap">
              <Button size="xs" variant="light" component={Link} to={`/projects/${project.id}`}>
                Open
              </Button>
              <Button size="xs" variant="default" component={Link} to={`/settings/projects/${project.id}`}>
                Edit
              </Button>
              <Button size="xs" variant="subtle" color="red" onClick={() => onDelete(project)}>
                Delete
              </Button>
            </Group>
          </Table.Td>
        </Table.Tr>
      )}
    />
  );
}
