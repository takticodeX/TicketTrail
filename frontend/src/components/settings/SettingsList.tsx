import { Alert, Button, Center, Group, Loader, Paper, Stack, Table, Text, Title } from '@mantine/core';
import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { errorMessage } from '../../api/errors';
import type { Page } from '../../api/types';

interface Props<T> {
  title: string;
  description: string;
  query: UseQueryResult<Page<T>>;
  addLabel: string;
  onAdd: () => void;
  emptyText: string;
  head: ReactNode;
  renderRow: (item: T) => ReactNode;
}

/** A settings page: title, add button, and the items in a table. */
export function SettingsList<T>({
  title,
  description,
  query,
  addLabel,
  onAdd,
  emptyText,
  head,
  renderRow,
}: Props<T>) {
  return (
    <Stack maw={1100}>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>{title}</Title>
          <Text c="dimmed" size="sm">
            {description}
          </Text>
        </div>
        <Button onClick={onAdd}>{addLabel}</Button>
      </Group>
      {query.isPending && (
        <Center p="xl">
          <Loader aria-label="Loading" />
        </Center>
      )}
      {query.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(query.error)}
        </Alert>
      )}
      {query.data && query.data.items.length === 0 && (
        <Paper withBorder p="xl" radius="md">
          <Text ta="center" c="dimmed">
            {emptyText}
          </Text>
        </Paper>
      )}
      {query.data && query.data.items.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={640}>
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>{head}</Table.Thead>
              <Table.Tbody>{query.data.items.map(renderRow)}</Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </Stack>
  );
}
