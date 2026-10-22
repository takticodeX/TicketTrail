import { Alert, Anchor, Badge, Button, Center, Loader, Pagination, Paper, Stack, Table, Text, Title } from '@mantine/core';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { listAllProjects, listTransfers, transferProject, type AdminProject } from '../../api/admin';
import { errorMessage } from '../../api/errors';
import { RunStatusBadge } from '../../components/RunStatusBadge';
import { TransferModal } from '../../components/TransferModal';
import { formatDateTime } from '../../lib/runs';

const PAGE_SIZE = 50;
const TRANSFERS_PAGE_SIZE = 20;

function TransferHistory() {
  const [page, setPage] = useState(1);
  const transfers = useQuery({
    queryKey: ['admin-transfers', page],
    queryFn: () => listTransfers(page, TRANSFERS_PAGE_SIZE),
    placeholderData: keepPreviousData,
  });
  const totalPages = transfers.data ? Math.max(1, Math.ceil(transfers.data.total / TRANSFERS_PAGE_SIZE)) : 1;

  return (
    <Stack gap="sm">
      <Title order={4}>Transfer history</Title>
      {transfers.isError && (
        <Alert color="red" variant="light" role="alert">
          {errorMessage(transfers.error)}
        </Alert>
      )}
      {transfers.data && transfers.data.items.length === 0 && (
        <Text size="sm" c="dimmed">
          No transfers yet.
        </Text>
      )}
      {transfers.data && transfers.data.items.length > 0 && (
        <Paper withBorder radius="md">
          <Table verticalSpacing="sm" aria-label="Transfer history">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>When</Table.Th>
                <Table.Th>By</Table.Th>
                <Table.Th>What</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {transfers.data.items.map((transfer) => (
                <Table.Tr key={transfer.id}>
                  <Table.Td>{formatDateTime(transfer.created_at)}</Table.Td>
                  <Table.Td>{transfer.admin?.email ?? '—'}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{transfer.summary}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      {totalPages > 1 && <Pagination total={totalPages} value={page} onChange={setPage} />}
    </Stack>
  );
}

/** Admins only: every project and who owns it, to hand projects over when someone leaves. */
export function AdminProjectsPage() {
  const [page, setPage] = useState(1);
  const [moving, setMoving] = useState<AdminProject | null>(null);
  const projects = useQuery({
    queryKey: ['admin-projects', page],
    queryFn: () => listAllProjects(page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  });
  const totalPages = projects.data ? Math.max(1, Math.ceil(projects.data.total / PAGE_SIZE)) : 1;

  return (
    <Stack maw={1100}>
      <div>
        <Title order={2}>Projects</Title>
        <Text c="dimmed" size="sm">
          Every project and its owner. Open one to see and change everything, or transfer it to a new owner, for
          example when a colleague leaves.
        </Text>
      </div>
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
        <Text size="sm" c="dimmed">
          No projects yet.
        </Text>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={720}>
            <Table verticalSpacing="sm" aria-label="All projects">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Project</Table.Th>
                  <Table.Th>Owner</Table.Th>
                  <Table.Th ta="right">Shared with</Table.Th>
                  <Table.Th>Last run</Table.Th>
                  <Table.Th aria-label="Actions" />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {projects.data.items.map((project) => (
                  <Table.Tr key={project.id}>
                    <Table.Td>
                      <Anchor component={Link} to={`/projects/${project.id}`} size="sm" fw={500}>
                        {project.name}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>
                      {project.owner ? (
                        <>
                          <Text size="sm">{project.owner.display_name}</Text>
                          <Text size="xs" c="dimmed">
                            {project.owner.email}
                          </Text>
                          {!project.owner.is_active && (
                            <Badge size="xs" color="gray" variant="light">
                              Turned off
                            </Badge>
                          )}
                        </>
                      ) : (
                        <Text size="sm">
                          {project.organization?.name}{' '}
                          <Badge size="xs" variant="outline">
                            Organization
                          </Badge>
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right">{project.shares}</Table.Td>
                    <Table.Td>
                      {project.last_run ? (
                        <RunStatusBadge status={project.last_run.status} />
                      ) : (
                        <Text size="sm" c="dimmed">
                          Never run
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {/* An organization's admins move its projects themselves. */}
                      {project.owner && (
                        <Button
                          size="xs"
                          variant="default"
                          aria-label={`Transfer ${project.name}`}
                          onClick={() => setMoving(project)}
                        >
                          Transfer
                        </Button>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {totalPages > 1 && <Pagination total={totalPages} value={page} onChange={setPage} />}
      <TransferHistory />
      <TransferModal
        opened={moving !== null}
        onClose={() => setMoving(null)}
        title={moving ? `Transfer "${moving.name}"` : 'Transfer'}
        explanation={
          moving &&
          `The new owner gets "${moving.name}" and the connections it uses. A connection ` +
            `${moving.owner?.display_name ?? 'the owner'} still uses in another project is copied instead.`
        }
        excludeUserId={moving?.owner?.id ?? ''}
        transfer={(toUserId) => transferProject(moving?.id ?? '', toUserId)}
      />
    </Stack>
  );
}
