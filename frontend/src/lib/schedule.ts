// Mirrors backend/app/core/cron.py: 5-field cron with a minimum interval,
// evaluated in the user's time zone.
import cronParser from 'cron-parser';
import cronstrue from 'cronstrue';

/** TT_MIN_SCHEDULE_MINUTES default; the API enforces the configured value. */
export const MIN_SCHEDULE_MINUTES = 5;

export const SCHEDULE_PRESETS = [
  { value: '*/15 * * * *', label: 'Every 15 minutes' },
  { value: '0 * * * *', label: 'Every hour' },
  { value: '0 8 * * *', label: 'Every day at 08:00' },
  { value: '0 8 * * 1-5', label: 'Weekdays at 08:00' },
] as const;

// Fewer runs than the API checks (1000): cron-parser is slow and this runs while
// typing. A too-short gap shows up within the first runs in practice, and the API
// still has the final word.
const CHECK_RUNS = 200;
const CHECK_HORIZON_MS = 400 * 24 * 60 * 60 * 1000;
const cache = new Map<string, string | null>();

export function normaliseCron(expression: string): string {
  return expression.trim().split(/\s+/).join(' ');
}

/** A reason the expression is invalid (same wording as the API), or null. */
export function cronError(expression: string, minIntervalMinutes = MIN_SCHEDULE_MINUTES): string | null {
  const key = `${minIntervalMinutes}|${normaliseCron(expression)}`;
  if (!cache.has(key)) cache.set(key, checkCron(expression, minIntervalMinutes));
  return cache.get(key) ?? null;
}

function checkCron(expression: string, minIntervalMinutes: number): string | null {
  const normalised = normaliseCron(expression);
  if (normalised.split(' ').length !== 5 || !normalised) {
    return 'must have 5 fields: minute hour day-of-month month day-of-week';
  }
  let runs;
  try {
    runs = cronParser.parseExpression(normalised, {
      currentDate: new Date(Date.UTC(2026, 0, 1)),
      tz: 'UTC',
    });
  } catch {
    return 'is not a valid cron expression';
  }
  const start = Date.UTC(2026, 0, 1);
  const minimum = minIntervalMinutes * 60_000;
  let previous = runs.next().getTime();
  for (let i = 0; i < CHECK_RUNS; i += 1) {
    const current = runs.next().getTime();
    if (current - previous < minimum) {
      return `must not run more often than every ${minIntervalMinutes} minutes`;
    }
    if (current - start > CHECK_HORIZON_MS) break;
    previous = current;
  }
  return null;
}

export function nextRuns(expression: string, timeZone: string, count = 3, now = new Date()): Date[] {
  const runs = cronParser.parseExpression(normaliseCron(expression), { currentDate: now, tz: timeZone });
  return Array.from({ length: count }, () => runs.next().toDate());
}

export function describeCron(expression: string): string {
  return cronstrue.toString(normaliseCron(expression), { use24HourTimeFormat: true });
}

export function formatRunTime(date: Date, timeZone: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  }).format(date);
}

/** Every IANA time zone the browser knows, plus UTC and the current value. */
export function timeZones(current: string): string[] {
  const zones = new Set(Intl.supportedValuesOf('timeZone'));
  zones.add('UTC');
  zones.add(current);
  return [...zones].sort();
}
