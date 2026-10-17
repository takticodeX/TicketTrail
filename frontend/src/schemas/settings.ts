import { z } from 'zod';

import { commentTemplateError } from '../lib/commentTemplate';
import { cronError } from '../lib/schedule';
import { ticketPatternError } from '../lib/ticketPattern';
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from './auth';

// Same rules as the API (backend/app/api/v1/schemas/), so errors show before saving.

/** Mirrors backend/app/core/urls.py normalise_https_url. */
export function httpsUrlError(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return 'Enter a full URL starting with https://';
  }
  if (url.protocol !== 'https:') return 'Must start with https://';
  if (!url.hostname) return 'Must include a host name';
  if (url.password) return 'Must not contain a password; enter the token in the secret field instead';
  if (url.hash) return 'Must not contain a #fragment';
  return null;
}

const name = z.string().trim().min(1, 'Name is required').max(100, 'At most 100 characters');
const httpsUrl = z
  .string()
  .trim()
  .max(2048)
  .superRefine((value, ctx) => {
    const error = httpsUrlError(value);
    if (error) ctx.addIssue({ code: z.ZodIssueCode.custom, message: error });
  });

function commitUrlTemplateError(value: string): string | null {
  if (!value) return null;
  if (!value.includes('{sha}')) return 'Must contain the {sha} placeholder';
  const rest = value.replaceAll('{sha}', '');
  if (rest.includes('{') || rest.includes('}')) return '{sha} is the only placeholder allowed';
  return httpsUrlError(value.replaceAll('{sha}', '0'.repeat(40)));
}

/** `hasSavedSecret`: editing a connection whose secret is stored, so the field may stay empty. */
export function gitConnectionSchema({ hasSavedSecret }: { hasSavedSecret: boolean }) {
  return z
    .object({
      name,
      repo_url: httpsUrl,
      auth_type: z.enum(['token', 'basic', 'none']),
      username: z.string().trim().max(255),
      secret: z.string().max(4096),
      commit_url_template: z
        .string()
        .trim()
        .max(2048)
        .superRefine((value, ctx) => {
          const error = commitUrlTemplateError(value);
          if (error) ctx.addIssue({ code: z.ZodIssueCode.custom, message: error });
        }),
    })
    .superRefine((values, ctx) => {
      if (values.auth_type === 'none') return;
      if (!values.username) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['username'], message: 'Username is required' });
      }
      if (!values.secret && !hasSavedSecret) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['secret'],
          message: values.auth_type === 'token' ? 'Token is required' : 'Password is required',
        });
      }
    });
}
export type GitConnectionValues = z.infer<ReturnType<typeof gitConnectionSchema>>;

export function azureConnectionSchema({ hasSavedSecret }: { hasSavedSecret: boolean }) {
  return z.object({
    name,
    organization_url: httpsUrl,
    azure_project: z.string().trim().min(1, 'Project is required').max(255),
    pat: hasSavedSecret
      ? z.string().max(4096)
      : z.string().min(1, 'Personal access token is required').max(4096),
  });
}
export type AzureConnectionValues = z.infer<ReturnType<typeof azureConnectionSchema>>;

// Mirrors the branch rule in backend/app/api/v1/schemas/projects.py.
// eslint-disable-next-line no-control-regex
const BRANCH = /^(?!-)(?!.*\.\.)(?!.*\/\/)(?!.*@\{)[^\s~^:?*[\\\x00-\x1f\x7f]+(?<![./])(?<!\.lock)$/;
const SHA = /^[0-9a-f]{7,40}$/i;

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

function custom(error: string | null, ctx: z.RefinementCtx, path?: string[]) {
  if (error) ctx.addIssue({ code: z.ZodIssueCode.custom, message: error, path });
}

export const projectSchema = z
  .object({
    name,
    git_connection_id: z.string().min(1, 'Pick a Git connection'),
    azure_connection_id: z.string().min(1, 'Pick an Azure connection'),
    branches: z
      .array(z.string().trim().max(255))
      .max(50, 'At most 50 branches')
      .superRefine((branches, ctx) => {
        const bad = branches.find((branch) => !BRANCH.test(branch));
        if (bad !== undefined) custom(`"${bad}" is not a valid branch name`, ctx);
      }),
    ticket_pattern: z.string().superRefine((value, ctx) => {
      const error = ticketPatternError(value);
      custom(error && `The pattern ${error}`, ctx);
    }),
    comment_template: z.string().superRefine((value, ctx) => {
      const error = commentTemplateError(value);
      custom(error && `The template ${error}`, ctx);
    }),
    start_mode: z.enum(['all', 'date', 'sha']),
    start_date: z.string(),
    start_sha: z.string().trim(),
    include_merge_commits: z.boolean(),
    schedule_cron: z.string(),
    schedule_enabled: z.boolean(),
    dry_run_default: z.boolean(),
  })
  .superRefine((values, ctx) => {
    if (values.start_mode === 'date' && !isIsoDate(values.start_date)) {
      custom('Pick a date', ctx, ['start_date']);
    }
    if (values.start_mode === 'sha' && !SHA.test(values.start_sha)) {
      custom('Enter a commit SHA (7 to 40 hex characters)', ctx, ['start_sha']);
    }
    if (values.schedule_cron.trim()) {
      const error = cronError(values.schedule_cron);
      custom(error && `The schedule ${error}`, ctx, ['schedule_cron']);
    } else if (values.schedule_enabled) {
      custom('Choose when to run, or turn the schedule off', ctx, ['schedule_cron']);
    }
  });
export type ProjectValues = z.infer<typeof projectSchema>;

export const profileSchema = z.object({
  display_name: z.string().trim().min(1, 'Display name is required').max(100),
  timezone: z.string().min(1, 'Pick a time zone'),
});
export type ProfileValues = z.infer<typeof profileSchema>;

export const passwordSchema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password'),
    new_password: z
      .string()
      .min(PASSWORD_MIN_LENGTH, `At least ${PASSWORD_MIN_LENGTH} characters`)
      .max(PASSWORD_MAX_LENGTH, `At most ${PASSWORD_MAX_LENGTH} characters`),
    confirm_password: z.string(),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  });
export type PasswordValues = z.infer<typeof passwordSchema>;
