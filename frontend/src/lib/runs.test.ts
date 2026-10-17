import { describe, expect, it } from 'vitest';

import { commitUrl, isRunActive, runDuration, workItemUrl } from './runs';

describe('runDuration', () => {
  it('formats seconds and minutes', () => {
    expect(runDuration({ started_at: '2026-10-17T10:00:00Z', finished_at: '2026-10-17T10:00:12Z' })).toBe('12 s');
    expect(runDuration({ started_at: '2026-10-17T10:00:00Z', finished_at: '2026-10-17T10:01:05Z' })).toBe(
      '1 min 05 s',
    );
  });

  it('is null until the run finishes', () => {
    expect(runDuration({ started_at: '2026-10-17T10:00:00Z', finished_at: null })).toBeNull();
  });
});

it('knows which runs are still in progress', () => {
  expect(isRunActive({ status: 'queued' })).toBe(true);
  expect(isRunActive({ status: 'running' })).toBe(true);
  expect(isRunActive({ status: 'partial' })).toBe(false);
});

it('links work items to Azure Boards', () => {
  expect(workItemUrl({ organization_url: 'https://dev.azure.com/acme', azure_project: 'Web App' }, 12)).toBe(
    'https://dev.azure.com/acme/Web%20App/_workitems/edit/12',
  );
});

it('links commits only when the host is known', () => {
  expect(commitUrl('https://github.com/acme/app/commit/{sha}', 'abc')).toBe('https://github.com/acme/app/commit/abc');
  expect(commitUrl('', 'abc')).toBeNull();
  expect(commitUrl(undefined, 'abc')).toBeNull();
});
