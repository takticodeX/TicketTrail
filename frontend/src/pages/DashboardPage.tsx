import { Paper, Stack, Text, Title } from '@mantine/core';

import { useAuth } from '../hooks/useAuth';

export function DashboardPage() {
  const { user } = useAuth();

  return (
    <Stack maw={960} mx="auto">
      <Title order={2}>Dashboard</Title>
      <Paper withBorder p="xl" radius="md">
        <Stack gap="xs" align="center" ta="center">
          <Text fw={600}>No projects yet</Text>
          <Text c="dimmed" size="sm" maw={420}>
            {user ? `Welcome, ${user.display_name}. ` : ''}
            Each project links a Git repository to an Azure DevOps board. Its sync status will
            show up here.
          </Text>
        </Stack>
      </Paper>
    </Stack>
  );
}
