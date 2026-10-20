import {
  ActionIcon,
  Anchor,
  AppShell,
  Burger,
  Group,
  Menu,
  NavLink,
  Text,
  Title,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Link, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from '../hooks/useAuth';

const SETTINGS_LINKS = [
  { to: '/settings/projects', label: 'Projects' },
  { to: '/settings/git', label: 'Git connections' },
  { to: '/settings/azure', label: 'Azure connections' },
  { to: '/settings/profile', label: 'Profile' },
];

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
  const { pathname } = useLocation();
  const [navOpen, { toggle, close }] = useDisclosure(false);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 230, breakpoint: 'sm', collapsed: { mobile: !navOpen } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={navOpen} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Anchor component={Link} to="/" c="inherit" underline="never">
              <Title order={3}>TicketTrail</Title>
            </Anchor>
          </Group>
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
                <Menu.Item component={Link} to="/settings/profile">
                  Profile
                </Menu.Item>
                <Menu.Item onClick={() => void logout()}>Log out</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" aria-label="Main navigation">
        <NavLink component={Link} to="/" label="Dashboard" active={pathname === '/'} onClick={close} />
        <NavLink label="Settings" defaultOpened childrenOffset="sm" active={false}>
          {SETTINGS_LINKS.map((link) => (
            <NavLink
              key={link.to}
              component={Link}
              to={link.to}
              label={link.label}
              active={pathname.startsWith(link.to)}
              onClick={close}
            />
          ))}
        </NavLink>
        {user?.role === 'admin' && (
          <NavLink label="Admin" defaultOpened childrenOffset="sm" active={false}>
            <NavLink
              component={Link}
              to="/admin/users"
              label="Users"
              active={pathname.startsWith('/admin/users')}
              onClick={close}
            />
            <NavLink
              component={Link}
              to="/admin/projects"
              label="Projects"
              active={pathname.startsWith('/admin/projects')}
              onClick={close}
            />
          </NavLink>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
