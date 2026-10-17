import { describe, expect, it } from 'vitest';

import { toFormValues } from '../pages/settings/projectForm';
import {
  azureConnectionSchema,
  gitConnectionSchema,
  httpsUrlError,
  passwordSchema,
  projectSchema,
} from './settings';

describe('httpsUrlError', () => {
  it.each(['https://github.com/acme/app.git', 'https://acme@dev.azure.com/acme/p/_git/r'])('accepts %s', (url) => {
    expect(httpsUrlError(url)).toBeNull();
  });

  it.each([
    ['http://github.com/acme/app', 'https://'],
    ['git@github.com:acme/app.git', 'full URL'],
    ['https://user:hunter2@github.com/acme/app', 'password'],
    ['https://github.com/acme/app#x', 'fragment'],
  ])('rejects %s', (url, reason) => {
    expect(httpsUrlError(url)).toContain(reason);
  });
});

const git = {
  name: 'Repo',
  repo_url: 'https://github.com/acme/app.git',
  auth_type: 'token' as const,
  username: 'x-access-token',
  secret: 'ghp_x',
  commit_url_template: '',
};

describe('gitConnectionSchema', () => {
  it('accepts a token connection', () => {
    expect(gitConnectionSchema({ hasSavedSecret: false }).safeParse(git).success).toBe(true);
  });

  it('needs a secret for a new token connection', () => {
    const result = gitConnectionSchema({ hasSavedSecret: false }).safeParse({ ...git, secret: '' });
    expect(result.error?.issues[0]?.path).toEqual(['secret']);
  });

  it('keeps the saved secret when the field is empty', () => {
    expect(gitConnectionSchema({ hasSavedSecret: true }).safeParse({ ...git, secret: '' }).success).toBe(true);
  });

  it('needs no credentials for a public repository', () => {
    const result = gitConnectionSchema({ hasSavedSecret: false }).safeParse({
      ...git,
      auth_type: 'none',
      username: '',
      secret: '',
    });
    expect(result.success).toBe(true);
  });

  it.each([
    ['https://gitea.example.com/commit/', '{sha}'],
    ['http://x/{sha}', 'https://'],
    ['https://x/{sha}/{branch}', 'only placeholder'],
  ])('checks the commit link %s', (template, reason) => {
    const result = gitConnectionSchema({ hasSavedSecret: false }).safeParse({
      ...git,
      commit_url_template: template,
    });
    expect(result.error?.issues[0]?.message).toContain(reason);
  });
});

describe('azureConnectionSchema', () => {
  const azure = { name: 'Board', organization_url: 'https://dev.azure.com/acme', azure_project: 'p', pat: 'x' };

  it('needs a PAT unless one is saved', () => {
    expect(azureConnectionSchema({ hasSavedSecret: false }).safeParse({ ...azure, pat: '' }).success).toBe(false);
    expect(azureConnectionSchema({ hasSavedSecret: true }).safeParse({ ...azure, pat: '' }).success).toBe(true);
  });
});

describe('projectSchema', () => {
  const valid = { ...toFormValues(undefined), name: 'P', git_connection_id: 'g', azure_connection_id: 'a' };

  it('accepts the defaults', () => {
    expect(projectSchema.safeParse(valid).success).toBe(true);
  });

  it.each([
    [{ branches: ['bad branch'] }, 'branches'],
    [{ branches: ['a..b'] }, 'branches'],
    [{ ticket_pattern: 'AB#\\d+' }, 'ticket_pattern'],
    [{ comment_template: '{nope}' }, 'comment_template'],
    [{ start_mode: 'date', start_date: '2026-02-30' }, 'start_date'],
    [{ start_mode: 'sha', start_sha: 'xyz' }, 'start_sha'],
    [{ schedule_cron: '* * * * *' }, 'schedule_cron'],
    [{ schedule_enabled: true, schedule_cron: '' }, 'schedule_cron'],
  ])('rejects %j', (override, field) => {
    const result = projectSchema.safeParse({ ...valid, ...override });
    expect(result.error?.issues.map((issue) => issue.path[0])).toContain(field);
  });

  it('accepts a date and a SHA start point', () => {
    expect(projectSchema.safeParse({ ...valid, start_mode: 'date', start_date: '2026-01-31' }).success).toBe(true);
    expect(projectSchema.safeParse({ ...valid, start_mode: 'sha', start_sha: 'ABCDEF1' }).success).toBe(true);
  });
});

describe('passwordSchema', () => {
  it('needs matching passwords of at least 10 characters', () => {
    const ok = { current_password: 'x', new_password: 'long-enough-1', confirm_password: 'long-enough-1' };
    expect(passwordSchema.safeParse(ok).success).toBe(true);
    expect(passwordSchema.safeParse({ ...ok, confirm_password: 'other' }).success).toBe(false);
    expect(passwordSchema.safeParse({ ...ok, new_password: 'short', confirm_password: 'short' }).success).toBe(false);
  });
});
