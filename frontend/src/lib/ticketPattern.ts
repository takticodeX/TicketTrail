// Mirrors the structural rules in backend/app/sync/parser.py. Python regex syntax
// itself is checked by the API (the live tester shows its error), since JavaScript
// regexes differ from Python's.

export const DEFAULT_TICKET_PATTERN = 'AB#(\\d+)';
export const MAX_PATTERN_LENGTH = 500;
const ID_GROUP_NAME = 'id';

const DIGITS_ONLY = /^(?:\\d|\[0-9\]|\[\\d\])(?:\+|\*|\?|\{\d+(?:,\d*)?\})?\??$/;
const NAMED_GROUP = /^\?P?<([A-Za-z_]\w*)>/;

interface Group {
  name: string | null;
  body: string;
}

function skipClass(pattern: string, index: number): number {
  let i = index + 1;
  if (pattern[i] === '^') i += 1;
  if (pattern[i] === ']') i += 1; // a leading ] is a literal
  while (i < pattern.length) {
    if (pattern[i] === '\\') {
      i += 2;
      continue;
    }
    if (pattern[i] === ']') return i + 1;
    i += 1;
  }
  return i;
}

export function capturingGroups(pattern: string): Group[] {
  const groups: Group[] = [];
  const stack: { start: number; name: string | null; capturing: boolean }[] = [];
  let i = 0;
  while (i < pattern.length) {
    const char = pattern[i];
    if (char === '\\') {
      i += 2;
      continue;
    }
    if (char === '[') {
      i = skipClass(pattern, i);
      continue;
    }
    if (char === '(') {
      const rest = pattern.slice(i + 1);
      const named = NAMED_GROUP.exec(rest);
      if (named) {
        stack.push({ start: i + 1 + named[0].length, name: named[1] ?? null, capturing: true });
        i += 1 + named[0].length;
        continue;
      }
      stack.push({ start: i + 1, name: null, capturing: !rest.startsWith('?') });
      i += 1;
      continue;
    }
    if (char === ')' && stack.length > 0) {
      const open = stack.pop();
      if (open?.capturing) groups.push({ name: open.name, body: pattern.slice(open.start, i) });
    }
    i += 1;
  }
  return groups;
}

/** A reason the pattern is invalid (same wording as the API), or null. */
export function ticketPatternError(pattern: string): string | null {
  if (!pattern) return 'must not be empty';
  if (pattern.length > MAX_PATTERN_LENGTH) return `must be at most ${MAX_PATTERN_LENGTH} characters`;
  const groups = capturingGroups(pattern);
  const named = groups.find((g) => g.name === ID_GROUP_NAME);
  let target: Group | undefined;
  if (named) target = named;
  else if (groups.length === 1) target = groups[0];
  else if (groups.length === 0) return 'needs one capture group for the ID, e.g. AB#(\\d+)';
  else return 'must have exactly one capture group, or name the ID group (?P<id>\\d+)';
  if (!target || !DIGITS_ONLY.test(target.body)) {
    return 'the ID group must capture digits only, e.g. (\\d+)';
  }
  return null;
}

/** Sample messages in the tester are separated by a line containing only "---". */
export function splitSamples(text: string): string[] {
  return text
    .split(/^---$/m)
    .map((sample) => sample.trim())
    .filter((sample) => sample.length > 0);
}
