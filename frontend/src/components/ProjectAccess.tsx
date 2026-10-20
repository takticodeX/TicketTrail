import { Badge, Text, type BadgeProps, type TextProps } from '@mantine/core';

import type { Project } from '../api/types';
import { ROLE_LABELS } from '../lib/access';

/** "Viewer" or "Editor" on projects shared with you; nothing on your own. */
export function RoleBadge({ project, ...props }: { project: Pick<Project, 'role'> } & BadgeProps) {
  if (project.role === 'owner') return null;
  return (
    <Badge size="sm" variant="light" color={project.role === 'editor' ? 'blue' : 'gray'} {...props}>
      {ROLE_LABELS[project.role]}
    </Badge>
  );
}

/** Who shared a project with you, or how many people you shared yours with. */
export function SharingLine({
  project,
  ...props
}: { project: Pick<Project, 'role' | 'owner' | 'organization' | 'shares'> } & TextProps) {
  if (project.organization) {
    const shared = project.shares > 0 ? ` · shared with ${project.shares}` : '';
    return (
      <Text size="sm" c="dimmed" {...props}>
        {project.organization.name}
        {project.role === 'owner' ? shared : ''}
      </Text>
    );
  }
  if (project.role !== 'owner') {
    return (
      <Text size="sm" c="dimmed" {...props}>
        Shared with you by {project.owner?.display_name ?? 'another user'}
      </Text>
    );
  }
  if (project.shares === 0) return null;
  return (
    <Text size="sm" c="dimmed" {...props}>
      Shared with {project.shares} {project.shares === 1 ? 'person' : 'people'}
    </Text>
  );
}
