import { Alert, Badge, Group, Loader, Paper, Stack, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { firstFieldMessage } from '../../api/errors';
import { testPattern } from '../../api/settings';
import { splitSamples, ticketPatternError } from '../../lib/ticketPattern';

export const DEFAULT_SAMPLES = [
  'Fix login redirect AB#123\n\nThe session cookie was dropped on redirect.',
  'Refactor billing (AB#45, AB#46)',
  'chore: bump dependencies',
].join('\n---\n');

interface Props {
  pattern: string;
  samples: string;
  onSamplesChange: (samples: string) => void;
}

/** Live tester: runs the pattern on the server (Python regex), as the sync will. */
export function PatternTester({ pattern, samples, onSamplesChange }: Props) {
  const [debounced] = useDebouncedValue({ pattern, samples }, 400);
  const sampleList = splitSamples(debounced.samples);
  const patternOk = ticketPatternError(debounced.pattern) === null;

  const query = useQuery({
    queryKey: ['test-pattern', debounced.pattern, sampleList],
    queryFn: ({ signal }) => testPattern(debounced.pattern, sampleList, signal),
    enabled: patternOk && sampleList.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: Infinity,
  });

  return (
    <Stack gap="xs">
      <Textarea
        label="Sample commit messages"
        description='Paste a few real messages. Separate them with a line containing only "---".'
        autosize
        minRows={4}
        maxRows={12}
        ff="monospace"
        value={samples}
        onChange={(event) => onSamplesChange(event.currentTarget.value)}
      />
      <Group gap="xs">
        <Text size="sm" fw={500}>
          Results
        </Text>
        {query.isFetching && <Loader size="xs" aria-label="Testing pattern" />}
      </Group>
      {!patternOk && (
        <Text size="sm" c="dimmed">
          Fix the pattern to see which IDs it finds.
        </Text>
      )}
      {patternOk && query.isError && (
        <Alert color="red" variant="light" role="alert">
          {firstFieldMessage(query.error)}
        </Alert>
      )}
      {patternOk && query.data && !query.isError && (
        <Stack gap={6} aria-label="Pattern results">
          {query.data.results.map((result, index) => (
            <Paper key={index} withBorder p="xs" radius="sm">
              <Group justify="space-between" wrap="nowrap" gap="sm">
                <Text size="sm" truncate ff="monospace">
                  {sampleList[index]?.split('\n')[0]}
                </Text>
                <Group gap={4} wrap="nowrap">
                  {result.error && (
                    <Badge color="red" variant="light" tt="none">
                      {result.error}
                    </Badge>
                  )}
                  {!result.error && result.ids.length === 0 && (
                    <Badge color="gray" variant="light" tt="none">
                      No reference
                    </Badge>
                  )}
                  {result.ids.map((id) => (
                    <Badge key={id} variant="light" tt="none">
                      #{id}
                    </Badge>
                  ))}
                </Group>
              </Group>
            </Paper>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
