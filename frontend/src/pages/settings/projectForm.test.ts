import { describe, expect, it } from 'vitest';

import type { GitConnection, Project } from '../../api/types';
import { sampleCommit, toFormValues, toProjectInput } from './projectForm';

const project: Project = {
  id: 'p1',
  name: 'App',
  git_connection_id: 'g1',
  azure_connection_id: 'a1',
  branches: ['main'],
  ticket_pattern: 'AB#(\\d+)',
  comment_template: '{subject} tt:{sha}',
  start_from: '2026-01-31',
  include_merge_commits: false,
  schedule_cron: '0 8 * * 1-5',
  schedule_enabled: true,
  dry_run_default: false,
  created_at: '',
  updated_at: '',
};

describe('form conversion', () => {
  it('round-trips a project', () => {
    const { id, created_at, updated_at, ...input } = project;
    expect(toProjectInput(toFormValues(project))).toEqual(input);
  });

  it('reads a SHA start point', () => {
    const values = toFormValues({ ...project, start_from: 'abcdef1' });
    expect(values.start_mode).toBe('sha');
    expect(values.start_sha).toBe('abcdef1');
  });

  it('sends null for no start point and no schedule', () => {
    const input = toProjectInput({ ...toFormValues(project), start_mode: 'all', schedule_cron: '  ' });
    expect(input.start_from).toBeNull();
    expect(input.schedule_cron).toBeNull();
  });
});

describe('sampleCommit', () => {
  it('builds the preview values from the connection', () => {
    const connection = {
      repo_url: 'https://github.com/acme/web-app.git',
      commit_url_pattern: 'https://github.com/acme/web-app/commit/{sha}',
    } as GitConnection;
    const sample = sampleCommit(connection, 'develop', 'Fix it AB#7\n\nBecause.\n---\nother');
    expect(sample.subject).toBe('Fix it AB#7');
    expect(sample.body).toBe('Because.');
    expect(sample.branch).toBe('develop');
    expect(sample.repo_name).toBe('web-app');
    expect(sample.commit_url).toBe(`https://github.com/acme/web-app/commit/${sample.sha}`);
  });
});
