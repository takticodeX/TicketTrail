import { Center, Paper, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export function AuthCard({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" radius="md" w="100%" maw={420}>
        <Stack gap="lg">
          <Stack gap={4}>
            <Text c="dimmed" size="sm" fw={600} tt="uppercase">
              TicketTrail
            </Text>
            <Title order={2}>{title}</Title>
            {subtitle && (
              <Text c="dimmed" size="sm">
                {subtitle}
              </Text>
            )}
          </Stack>
          {children}
        </Stack>
      </Paper>
    </Center>
  );
}
