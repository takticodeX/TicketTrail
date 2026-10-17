import {
  ActionIcon,
  Anchor,
  AppShell,
  Group,
  Menu,
  Text,
  Title,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { Link, Outlet } from 'react-router-dom';

import { useAuth } from '../hooks/useAuth';

function ThemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme('light', { getInitialValueInEffect: true });
  const next = computed === 'dark' ? 'light' : 'dark';
  return (
    <ActionIcon
      variant="default"
      size="lg"
      onClick={() => setColorScheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      <span aria-hidden>{computed === 'dark' ? '☀' : '☾'}</span>
    </ActionIcon>
  );
}

export function AppLayout() {
  const { user, logout } = useAuth();

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Anchor component={Link} to="/" c="inherit" underline="never">
            <Title order={3}>TicketTrail</Title>
          </Anchor>
          <Group gap="sm" wrap="nowrap">
            <ThemeToggle />
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <UnstyledButton aria-label="Account menu">
                  <Text fw={500} truncate maw={200}>
                    {user?.display_name}
                  </Text>
                </UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user?.email}</Menu.Label>
                <Menu.Item onClick={() => void logout()}>Log out</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
