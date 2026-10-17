import { describe, expect, it } from 'vitest';

import { DEFAULT_TICKET_PATTERN, splitSamples, ticketPatternError } from './ticketPattern';

// The same cases as backend/tests/unit/test_parser.py, so both sides agree.
describe('ticketPatternError', () => {
  it.each([
    DEFAULT_TICKET_PATTERN,
    '#(\\d+)',
    '(?:fixes|refs)\\s+#(\\d+)',
    'PROJ-(\\d+)',
    '(?P<id>\\d+)@(\\w+)',
    '(?<id>[0-9]{1,6})!',
    '(?i:task)\\s*(\\d+)',
    '\\[(\\d+)\\]',
    '(?:[(]x[)])?#(\\d+)',
    '(\\w+)-(?P<id>\\d+)',
  ])('accepts %s', (pattern) => {
    expect(ticketPatternError(pattern)).toBeNull();
  });

  it.each([
    ['', 'empty'],
    ['AB#\\d+', 'needs one capture group'],
    ['(AB)#(\\d+)', 'exactly one capture group'],
    ['AB#(\\w+)', 'digits only'],
    ['AB#(\\d+[a-z])', 'digits only'],
    ['AB#(.+)', 'digits only'],
    ['(?P<ticket>\\d+)-(\\d+)', 'exactly one capture group'],
    ['a'.repeat(501), 'at most 500'],
  ])('rejects %s', (pattern, reason) => {
    expect(ticketPatternError(pattern)).toContain(reason);
  });
});

describe('splitSamples', () => {
  it('splits on lines that contain only ---', () => {
    expect(splitSamples('one AB#1\n\nbody\n---\ntwo\n---\n\n')).toEqual(['one AB#1\n\nbody', 'two']);
  });

  it('keeps --- inside a line', () => {
    expect(splitSamples('a --- b')).toEqual(['a --- b']);
  });
});
