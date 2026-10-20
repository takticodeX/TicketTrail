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
import { RoleBadge, SharingLine } from '../components/ProjectAccess';
import { RunStatusBadge } from '../components/RunStatusBadge';
import { SyncNowButton } from '../components/SyncNowButton';
import { useAuth } from '../hooks/useAuth';
import { useDryRun } from '../hooks/useDryRun';
import { useProjects } from '../hooks/useSettings';
import { canEdit } from '../lib/access';
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
          <Group gap={6} wrap="nowrap">
            <RoleBadge project={project} />
            {last && <RunStatusBadge status={last.status} />}
          </Group>
        </Group>
        <SharingLine project={project} size="xs" mt={-8} />
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
          {canEdit(project) && <SyncNowButton project={project} onDryRun={dryRun.start} size="xs" />}
        </Group>
      </Stack>
    </Card>
  );
}

function ProjectGrid({ projects, timeZone }: { projects: Project[]; timeZone: string }) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} timeZone={timeZone} />
      ))}
    </SimpleGrid>
  );
}

/** One card per project: last run, next scheduled run, comments posted, Sync now / Dry run. */
export function DashboardPage() {
  const { user } = useAuth();
  const projects = useProjects();
  const timeZone = user?.timezone ?? 'UTC';
  const all = projects.data?.items ?? [];
  const own = all.filter((p) => p.role === 'owner');
  const shared = all.filter((p) => p.role !== 'owner');

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
      {projects.data && own.length === 0 && (
        <Card withBorder p="xl" radius="md">
          <Stack gap="xs" align="center" ta="center">
            <Text fw={600}>{shared.length > 0 ? 'No projects of your own yet' : 'No projects yet'}</Text>
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
      {own.length > 0 && <ProjectGrid projects={own} timeZone={timeZone} />}
      {shared.length > 0 && (
        <>
          <Title order={4} mt="md">
            Shared with me
          </Title>
          <ProjectGrid projects={shared} timeZone={timeZone} />
        </>
      )}
    </Stack>
  );
}
