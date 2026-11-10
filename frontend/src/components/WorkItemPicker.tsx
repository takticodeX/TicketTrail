import { Group, Select, Text } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useState } from 'react';

import type { WorkItemOption } from '../api/types';
import { useWorkItemSearch } from '../hooks/useRuns';

/**
 * A searchable list of the board's work items (ID, title, type, state), open ones first.
 * Typing searches the board by words of the title or by ID.
 */
export function WorkItemPicker({
  projectId,
  onPick,
  label,
  autoFocus = false,
}: {
  projectId: string;
  onPick: (workItemId: string) => void;
  label: string;
  autoFocus?: boolean;
}) {
  const [search, setSearch] = useState('');
  const [opened, setOpened] = useState(autoFocus);
  const [query] = useDebouncedValue(search.trim(), 300);
  const result = useWorkItemSearch(projectId, query, opened);
  const options = result.data?.ok ? result.data.items : [];
  const byId = new Map<string, WorkItemOption>(options.map((w) => [w.id, w]));

  return (
    <Select
      aria-label={label}
      placeholder="Pick a work item"
      size="xs"
      w={280}
      searchable
      autoFocus={autoFocus}
      defaultDropdownOpened={autoFocus}
      searchValue={search}
      onSearchChange={setSearch}
      onDropdownOpen={() => setOpened(true)}
      // The board does the searching: show what it found as it is.
      filter={({ options: all }) => all}
      data={options.map((w) => ({ value: w.id, label: `#${w.id} · ${w.title}` }))}
      value={null}
      onChange={(value) => value && onPick(value)}
      nothingFoundMessage={
        result.isFetching
          ? 'Searching…'
          : result.data && !result.data.ok
            ? (result.data.error ?? 'The board could not be searched.')
            : 'No work item found'
      }
      renderOption={({ option }) => {
        const item = byId.get(option.value);
        return (
          <div>
            <Text size="sm" c={item?.closed ? 'dimmed' : undefined} lineClamp={1}>
              {option.label}
            </Text>
            {item && (
              <Group gap={6}>
                <Text size="xs" c="dimmed">
                  {item.type} · {item.state}
                </Text>
              </Group>
            )}
          </div>
        );
      }}
    />
  );
}
