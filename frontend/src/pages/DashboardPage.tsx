import {
  Alert,
  Anchor,
  Button,
  Card,
  Center,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Link } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import type { Project } from '../api/types';
import { RunStatusBadge } from '../components/RunStatusBadge';
import { SyncNowButton } from '../components/SyncNowButton';
import { useAuth } from '../hooks/useAuth';
import { useDryRun } from '../hooks/useDryRun';
import { useProjects } from '../hooks/useSettings';
import { formatDateTime } from '../lib/runs';
import { formatRunTime } from '../lib/schedule';

function ProjectCard({ project, timeZone }: { project: Project; timeZone: string }) {
  const dryRun = useDryRun(project.id);
  const last = project.last_run;
  const posted = project.comments_posted ?? 0;

  return (
    <Card withBorder radius="md" padding="lg" aria-label={project.name}>
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Anchor component={Link} to={`/projects/${project.id}`} fw={600} size="lg" lineClamp={1}>
            {project.name}
          </Anchor>
          {last && <RunStatusBadge status={last.status} />}
        </Group>
        <Stack gap={2}>
          <Text size="sm">
            {last ? (
              <>
                Last run:{' '}
                <Anchor component={Link} to={`/projects/${project.id}/runs/${last.id}`} size="sm">
                  {formatDateTime(last.started_at ?? last.created_at)}
                </Anchor>
                {last.dry_run && ' (dry run)'}
              </>
            ) : (
              <Text span c="dimmed" size="sm">
                Never run
              </Text>
            )}
          </Text>
          <Text size="sm">
            {project.next_run_at ? (
              <>Next run: {formatRunTime(new Date(project.next_run_at), timeZone)}</>
            ) : (
              <Text span c="dimmed" size="sm">
                No schedule: manual only
              </Text>
            )}
          </Text>
          <Text size="sm">
            {posted} {posted === 1 ? 'comment' : 'comments'} posted
          </Text>
        </Stack>
        <Group gap="xs" mt="xs">
          <Button size="xs" variant="default" onClick={dryRun.start} loading={dryRun.pending}>
            Dry run
          </Button>
          <SyncNowButton project={project} onDryRun={dryRun.start} size="xs" />
        </Group>
      </Stack>
    </Card>
  );
}

/** One card per project: last run, next scheduled run, comments posted, Sync now / Dry run. */
export function DashboardPage() {
  const { user } = useAuth();
  const projects = useProjects();
  const timeZone = user?.timezone ?? 'UTC';

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
            <ProjectCard key={project.id} project={project} timeZone={timeZone} />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
