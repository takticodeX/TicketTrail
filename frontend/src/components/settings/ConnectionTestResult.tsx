import { Alert, Badge, Group, Text } from '@mantine/core';

import type { AzureTestResult, GitTestResult } from '../../api/types';

const MAX_BRANCH_BADGES = 30;

export function GitTestResultView({ result }: { result: GitTestResult }) {
  if (!result.ok) {
    return (
      <Alert color="red" variant="light" title="Connection failed" role="alert">
        {result.error}
      </Alert>
    );
  }
  const shown = result.branches.slice(0, MAX_BRANCH_BADGES);
  return (
    <Alert color="teal" variant="light" title="Connection works" role="status">
      <Text size="sm" mb="xs">
        Found {result.branches.length} {result.branches.length === 1 ? 'branch' : 'branches'}
        {result.default_branch && (
          <>
            {' '}
            · default: <strong>{result.default_branch}</strong>
          </>
        )}
      </Text>
      <Group gap={6}>
        {shown.map((branch) => (
          <Badge key={branch} variant="outline" tt="none">
            {branch}
          </Badge>
        ))}
        {result.branches.length > shown.length && (
          <Text size="xs" c="dimmed">
            and {result.branches.length - shown.length} more
          </Text>
        )}
      </Group>
    </Alert>
  );
}

export function AzureTestResultView({ result }: { result: AzureTestResult }) {
  if (!result.ok) {
    return (
      <Alert color="red" variant="light" title="Connection failed" role="alert">
        {result.error}
      </Alert>
    );
  }
  return (
    <Alert color="teal" variant="light" title="Connection works" role="status">
      Found the project <strong>{result.project_name}</strong>.
    </Alert>
  );
}
