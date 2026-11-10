import type { BoardKind, ProjectBoardSummary } from '../api/types';

/** What each kind of board is called in the UI. */
export const BOARD_LABELS: Record<BoardKind, string> = {
  azure: 'Azure DevOps',
};

/** What the URL and the scope of a connection are, per kind. */
export const BOARD_FIELDS: Record<BoardKind, { url: string; scope: string; secret: string }> = {
  azure: { url: 'Organization URL', scope: 'Project', secret: 'Personal access token' },
};

/** "https://dev.azure.com/acme · Web", for lists of connections. */
export function boardDetail(connection: Pick<ProjectBoardSummary, 'url' | 'scope'>): string {
  return `${connection.url} · ${connection.scope}`;
}

/** The board's page for one work item. */
export function workItemUrl(connection: Pick<ProjectBoardSummary, 'kind' | 'url' | 'scope'>, id: string): string {
  return `${connection.url}/${encodeURIComponent(connection.scope)}/_workitems/edit/${encodeURIComponent(id)}`;
}
