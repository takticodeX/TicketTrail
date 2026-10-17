import { Badge } from '@mantine/core';

import type { RunStatus } from '../api/types';
import { STATUS_COLORS, STATUS_LABELS } from '../lib/runs';

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge color={STATUS_COLORS[status]} variant="light">
      {STATUS_LABELS[status]}
    </Badge>
  );
}
