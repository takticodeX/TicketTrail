import type { GitConnection, Project, ProjectInput } from '../../api/types';
import { DEFAULT_COMMENT_TEMPLATE, type TemplateValues } from '../../lib/commentTemplate';
import { DEFAULT_TICKET_PATTERN, splitSamples } from '../../lib/ticketPattern';
import type { ProjectValues } from '../../schemas/settings';

const SHA = /^[0-9a-f]{7,40}$/;

export function toFormValues(project: Project | undefined): ProjectValues {
  const start = project?.start_from ?? null;
  return {
    name: project?.name ?? '',
    git_connection_id: project?.git_connection_id ?? '',
    azure_connection_id: project?.azure_connection_id ?? '',
    branches: project?.branches ?? [],
    ticket_pattern: project?.ticket_pattern ?? DEFAULT_TICKET_PATTERN,
    comment_template: project?.comment_template ?? DEFAULT_COMMENT_TEMPLATE,
    start_mode: start === null ? 'all' : SHA.test(start) ? 'sha' : 'date',
    start_date: start !== null && !SHA.test(start) ? start : '',
    start_sha: start !== null && SHA.test(start) ? start : '',
    include_merge_commits: project?.include_merge_commits ?? false,
    schedule_cron: project?.schedule_cron ?? '',
    schedule_enabled: project?.schedule_enabled ?? false,
    dry_run_default: project?.dry_run_default ?? false,
  };
}

export function toProjectInput(values: ProjectValues): ProjectInput {
  const startFrom =
    values.start_mode === 'date'
      ? values.start_date
      : values.start_mode === 'sha'
        ? values.start_sha.toLowerCase()
        : null;
  return {
    name: values.name,
    git_connection_id: values.git_connection_id,
    azure_connection_id: values.azure_connection_id,
    branches: values.branches,
    ticket_pattern: values.ticket_pattern,
    comment_template: values.comment_template,
    start_from: startFrom,
    include_merge_commits: values.include_merge_commits,
    schedule_cron: values.schedule_cron.trim() || null,
    schedule_enabled: values.schedule_enabled,
    dry_run_default: values.dry_run_default,
  };
}

const SAMPLE_SHA = '3f9a1c27b4e85d60a1b2c3d4e5f60718293a4b5c';

/** Sample values for the template preview, using the project's own settings where possible. */
export function sampleCommit(
  connection: Pick<GitConnection, 'repo_url' | 'commit_url_pattern'> | null | undefined,
  branch: string,
  samples: string,
): TemplateValues {
  const message = splitSamples(samples)[0] ?? 'Fix login redirect AB#123';
  const [subject = '', ...rest] = message.split('\n');
  const repoName =
    connection?.repo_url.replace(/\/+$/, '').replace(/\.git$/, '').split('/').pop() ?? 'repository';
  return {
    sha: SAMPLE_SHA,
    short_sha: SAMPLE_SHA.slice(0, 7),
    message,
    subject,
    body: rest.join('\n').trim(),
    author_name: 'Ada Lovelace',
    author_email: 'ada@example.com',
    author_date: '2026-10-17 14:32 UTC',
    branch,
    repo_name: repoName,
    commit_url: connection?.commit_url_pattern.replaceAll('{sha}', SAMPLE_SHA) ?? '',
  };
}

/** Which wizard step shows each field, so a server error can jump to it. */
export const FIELD_STEP: Record<string, number> = {
  name: 0,
  git_connection_id: 0,
  branches: 1,
  azure_connection_id: 2,
  ticket_pattern: 3,
  comment_template: 4,
  start_from: 5,
  start_mode: 5,
  start_date: 5,
  start_sha: 5,
  include_merge_commits: 5,
  dry_run_default: 5,
  schedule_cron: 6,
  schedule_enabled: 6,
};
