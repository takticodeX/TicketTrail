import { Anchor, Center, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <Center mih="60vh">
      <Stack align="center" gap="xs">
        <Title order={2}>Page not found</Title>
        <Text c="dimmed">The page you are looking for does not exist.</Text>
        <Anchor component={Link} to="/">
          Back to the dashboard
        </Anchor>
      </Stack>
    </Center>
  );
}
