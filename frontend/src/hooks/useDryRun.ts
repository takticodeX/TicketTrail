import { notifications } from '@mantine/notifications';
import { useNavigate } from 'react-router-dom';

import { errorMessage } from '../api/errors';
import { useStartSync } from './useRuns';

/** Start a dry run for the project and open its page. */
export function useDryRun(projectId: string) {
  const navigate = useNavigate();
  const startSync = useStartSync(projectId);
  const start = () =>
    startSync.mutate(true, {
      onSuccess: ({ run_id }) => navigate(`/projects/${projectId}/runs/${run_id}`),
      onError: (error) => notifications.show({ color: 'red', message: errorMessage(error) }),
    });
  return { start, pending: startSync.isPending };
}
