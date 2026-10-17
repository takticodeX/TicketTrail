import { List, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { useState } from 'react';

import {
  SCHEDULE_PRESETS,
  cronError,
  describeCron,
  formatRunTime,
  nextRuns,
  normaliseCron,
} from '../../lib/schedule';

const CUSTOM = 'custom';

interface Props {
  cron: string;
  onCronChange: (cron: string) => void;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  error?: string;
  timeZone: string;
}

function presetFor(cron: string): string {
  const normalised = normaliseCron(cron);
  return SCHEDULE_PRESETS.find((preset) => preset.value === normalised)?.value ?? CUSTOM;
}

/** Presets plus a custom cron, with the next three runs in the user's time zone. */
export function ScheduleField({ cron, onCronChange, enabled, onEnabledChange, error, timeZone }: Props) {
  const [mode, setMode] = useState(() => (cron ? presetFor(cron) : SCHEDULE_PRESETS[1].value));
  const valid = cron.trim() !== '' && cronError(cron) === null;

  const onModeChange = (value: string | null) => {
    if (!value) return;
    setMode(value);
    if (value !== CUSTOM) onCronChange(value);
  };

  return (
    <Stack gap="sm">
      <Switch
        label="Sync on a schedule"
        description="Off: the project only syncs when you press Sync now."
        checked={enabled}
        onChange={(event) => {
          const on = event.currentTarget.checked;
          onEnabledChange(on);
          if (on && !cron) onCronChange(mode === CUSTOM ? '' : mode);
        }}
      />
      <Select
        label="When"
        allowDeselect={false}
        data={[...SCHEDULE_PRESETS.map((p) => ({ value: p.value, label: p.label })), { value: CUSTOM, label: 'Custom (cron)' }]}
        value={mode}
        onChange={onModeChange}
        disabled={!enabled}
      />
      {mode === CUSTOM && (
        <TextInput
          label="Cron expression"
          description="5 fields: minute hour day-of-month month day-of-week, e.g. 30 7 * * 1-5"
          ff="monospace"
          value={cron}
          onChange={(event) => onCronChange(event.currentTarget.value)}
          error={error}
          disabled={!enabled}
        />
      )}
      {mode !== CUSTOM && error && (
        <Text size="sm" c="red">
          {error}
        </Text>
      )}
      {enabled && valid && (
        <div aria-label="Next runs">
          <Text size="sm" fw={500}>
            {describeCron(cron)}
          </Text>
          <Text size="xs" c="dimmed" mb={4}>
            Next runs ({timeZone}):
          </Text>
          <List size="sm" spacing={2}>
            {nextRuns(cron, timeZone).map((run) => (
              <List.Item key={run.toISOString()}>{formatRunTime(run, timeZone)}</List.Item>
            ))}
          </List>
        </div>
      )}
    </Stack>
  );
}
