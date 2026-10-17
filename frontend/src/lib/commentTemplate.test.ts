import { describe, expect, it } from 'vitest';

import {
  DEFAULT_COMMENT_TEMPLATE,
  commentTemplateError,
  renderTemplate,
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

  it('renders the default template', () => {
    const rendered = renderTemplate(DEFAULT_COMMENT_TEMPLATE, values);
    expect(rendered).toContain('[`abc123d`](https://github.com/acme/app/commit/abc123def456)');
    expect(rendered).toContain('tt:abc123def456');
    expect(rendered.match(/tt:/g)).toHaveLength(1);
  });
});
