import { Alert, Anchor, Button, Card, Center, Loader, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import { useAuth } from '../hooks/useAuth';
import { useProjects } from '../hooks/useSettings';

/** One card per project. Last run status and Sync now buttons arrive with Milestone 6. */
export function DashboardPage() {
  const { user } = useAuth();
  const projects = useProjects();

  return (
    <Stack maw={1100}>
      <Title order={2}>Dashboard</Title>
      {projects.isPending && (
        <Center p="xl">
          <Loader aria-label="Loading" />
        </Center>
      )}
      {projects.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(projects.error)}
        </Alert>
      )}
      {projects.data && projects.data.items.length === 0 && (
        <Card withBorder p="xl" radius="md">
          <Stack gap="xs" align="center" ta="center">
            <Text fw={600}>No projects yet</Text>
            <Text c="dimmed" size="sm" maw={460}>
              {user ? `Welcome, ${user.display_name}. ` : ''}A project links a Git repository to an
              Azure DevOps board.
            </Text>
            <Button component={Link} to="/settings/projects/new" mt="xs">
              Create a project
            </Button>
          </Stack>
        </Card>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {projects.data.items.map((project) => (
            <Card key={project.id} withBorder radius="md" padding="lg">
              <Stack gap="xs">
                <Anchor component={Link} to={`/projects/${project.id}`} fw={600} size="lg">
                  {project.name}
                </Anchor>
                <Text size="sm" c="dimmed">
                  {project.branches.length > 0 ? project.branches.join(', ') : 'Default branch'}
                </Text>
                <Button component={Link} to={`/projects/${project.id}`} variant="light" mt="xs">
                  Open
                </Button>
              </Stack>
            </Card>
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
