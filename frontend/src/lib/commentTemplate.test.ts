import { describe, expect, it } from 'vitest';

import {
  DEFAULT_COMMENT_TEMPLATE,
  commentTemplateError,
  escapeMarkdown,
  renderTemplate,
  truncate,
  type TemplateValues,
} from './commentTemplate';

const values: TemplateValues = {
  sha: 'abc123def456',
  short_sha: 'abc123d',
  message: 'Fix login AB#1',
  subject: 'Fix login AB#1',
  body: '',
  author_name: 'Ada',
  author_email: 'ada@example.com',
  author_date: '2026-10-17 14:32',
  branch: 'main',
  repo_name: 'app',
  commit_url: 'https://github.com/acme/app/commit/abc123def456',
};

describe('commentTemplateError', () => {
  it('accepts the default template', () => {
    expect(commentTemplateError(DEFAULT_COMMENT_TEMPLATE)).toBeNull();
  });

  it('accepts escaped braces', () => {
    expect(commentTemplateError('{{not a variable}} {sha}')).toBeNull();
  });

  // The same cases as backend/tests/unit/test_template.py.
  it.each([
    ['', 'empty'],
    ['   \n', 'empty'],
    ['{author}', 'unknown variable'],
    ['{}', 'unknown variable'],
    ['{sha', 'unmatched'],
    ['sha}', 'unmatched'],
    ['{sha:>10}', 'format options'],
    ['{sha!r}', 'format options'],
    ['x'.repeat(10_001), 'at most'],
  ])('rejects %j', (template, reason) => {
    expect(commentTemplateError(template)).toContain(reason);
  });
});

// The same cases as backend/tests/unit/test_template.py, so the preview matches the sync.
describe('escapeMarkdown', () => {
  it('neutralises HTML and links', () => {
    expect(escapeMarkdown('<img src=x onerror=alert(1)> [click](https://evil.example)')).toBe(
      '\\<img src=x onerror=alert\\(1\\)\\> \\[click\\]\\(https://evil.example\\)',
    );
  });

  it('keeps ticket references readable', () => {
    expect(escapeMarkdown('Fix AB#123 and #45')).toBe('Fix AB#123 and #45');
  });

  it('keeps line breaks and paragraphs', () => {
    expect(escapeMarkdown('one\ntwo\n\n\n   three\r\nfour')).toBe('one  \ntwo\n\nthree  \nfour');
  });

  it('truncates long messages to 10,000 characters', () => {
    const cut = truncate('x'.repeat(20_000));
    expect(cut).toHaveLength(10_000);
    expect(cut.endsWith('…')).toBe(true);
  });
});

describe('renderTemplate', () => {
  it('fills in the variables', () => {
    expect(renderTemplate('{short_sha} on {branch}: {subject} tt:{sha}', values)).toBe(
      'abc123d on main: Fix login AB#1 tt:abc123def456',
    );
  });

  it('turns escaped braces into literal braces', () => {
    expect(renderTemplate('{{x}} tt:{sha}', values)).toBe('{x} tt:abc123def456');
  });

  it('adds the tt:{sha} marker when the template drops it', () => {
    expect(renderTemplate('{subject}', values)).toBe('Fix login AB#1\n\n<sub>tt:abc123def456</sub>');
  });

  it('escapes the message like the sync does', () => {
    const message = '# Not a heading\n- not a list\n1. not ordered\n> not a quote\n*bold* _it_ `code`';
    expect(renderTemplate('{message} tt:{sha}', { ...values, message })).toBe(
      '\\# Not a heading  \n\\- not a list  \n1\\. not ordered  \n\\> not a quote  \n' +
        '\\*bold\\* \\_it\\_ \\`code\\` tt:abc123def456',
    );
  });

  it('renders the default template', () => {
    const rendered = renderTemplate(DEFAULT_COMMENT_TEMPLATE, values);
    expect(rendered).toContain('[`abc123d`](https://github.com/acme/app/commit/abc123def456)');
    expect(rendered).toContain('tt:abc123def456');
    expect(rendered.match(/tt:/g)).toHaveLength(1);
  });
});
