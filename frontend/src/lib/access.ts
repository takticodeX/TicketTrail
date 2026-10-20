// What the signed-in user may do on a project. The API enforces the same rules;
// these only decide which buttons to show.
import type { Project, ProjectRole, SyncRun } from '../api/types';

export const ROLE_LABELS: Record<ProjectRole, string> = {
  owner: 'Owner',
  editor: 'Editor',
  viewer: 'Viewer',
};

export const ROLE_DESCRIPTIONS: Record<Exclude<ProjectRole, 'owner'>, string> = {
  viewer: 'sees the project and its runs, and can start dry runs.',
  editor: 'also runs real syncs, changes the settings and manages the run history.',
};

export const isOwner = (project: Pick<Project, 'role'>) => project.role === 'owner';

export const canEdit = (project: Pick<Project, 'role'>) =>
  project.role === 'owner' || project.role === 'editor';

/** Editors manage every run; a viewer only the dry runs they started. */
export function canManageRun(
  project: Pick<Project, 'role'>,
  run: Pick<SyncRun, 'dry_run' | 'triggered_by'>,
  userId: string | undefined,
): boolean {
  return canEdit(project) || (run.dry_run && userId !== undefined && run.triggered_by?.id === userId);
}
