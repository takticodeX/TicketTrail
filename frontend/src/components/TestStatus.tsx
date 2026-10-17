import { Badge, Tooltip } from '@mantine/core';

const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

/** The result of a connection's last test, as a small badge. */
export function TestStatus({ ok, at }: { ok: boolean | null; at: string | null }) {
  if (ok === null || at === null) {
    return (
      <Badge variant="light" color="gray">
        Not tested
      </Badge>
    );
  }
  return (
    <Tooltip label={`Last tested ${formatter.format(new Date(at))}`}>
      <Badge variant="light" color={ok ? 'teal' : 'red'}>
        {ok ? 'Working' : 'Failing'}
      </Badge>
    </Tooltip>
  );
}
