import { describe, expect, it } from 'vitest';

import { SCHEDULE_PRESETS, cronError, describeCron, formatRunTime, nextRuns } from './schedule';

// The same cases as backend/tests/unit/test_cron.py.
describe('cronError', () => {
  it.each(['*/15 * * * *', '0 * * * *', '0 8 * * *', '0 8 * * 1-5', '*/5 * * * *', '30 2 1 * *'])(
    'accepts %s',
    (expression) => {
      expect(cronError(expression)).toBeNull();
    },
  );

  it('accepts every preset', () => {
    for (const preset of SCHEDULE_PRESETS) expect(cronError(preset.value)).toBeNull();
  });

  it.each(['* * * *', '0 0 * * * *', '@hourly', '', '0 8 * * MON-FRI extra'])('needs 5 fields: %j', (expression) => {
    expect(cronError(expression)).toContain('5 fields');
  });

  it.each(['61 * * * *', '0 25 * * *', 'a b c d e'])('rejects invalid values: %s', (expression) => {
    expect(cronError(expression)).toContain('not a valid');
  });

  it.each(['* * * * *', '*/4 * * * *', '0,1 8 * * *', '0,2 0 1 * *'])(
    'enforces the minimum interval: %s',
    (expression) => {
      expect(cronError(expression)).toContain('every 5 minutes');
    },
  );

  it('takes the minimum interval as a parameter', () => {
    expect(cronError('* * * * *', 1)).toBeNull();
    expect(cronError('*/15 * * * *', 30)).toContain('every 30 minutes');
  });
});

describe('nextRuns', () => {
  it('evaluates the expression in the given time zone', () => {
    const now = new Date('2026-10-16T12:00:00Z'); // a Friday
    const runs = nextRuns('0 8 * * 1-5', 'Europe/Rome', 3, now);
    // 08:00 in Rome; Rome is UTC+2 until Sunday 25 October, then UTC+1.
    expect(runs.map((run) => run.toISOString())).toEqual([
      '2026-10-19T06:00:00.000Z',
      '2026-10-20T06:00:00.000Z',
      '2026-10-21T06:00:00.000Z',
    ]);
    expect(formatRunTime(runs[0] as Date, 'Europe/Rome', 'en-GB')).toBe('Mon, 19 Oct 2026, 08:00');
  });
});

describe('describeCron', () => {
  it('says the schedule in plain language', () => {
    expect(describeCron('0 8 * * 1-5')).toBe('At 08:00, Monday through Friday');
    expect(describeCron('*/15 * * * *')).toBe('Every 15 minutes');
  });
});
