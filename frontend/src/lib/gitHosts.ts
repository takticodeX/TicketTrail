// Mirrors backend/app/integrations/git/hosts.py.

export type GitHost = 'azure_repos' | 'github' | 'gitlab' | 'bitbucket' | 'generic';

export function detectHost(repoUrl: string): GitHost {
  let host: string;
  try {
    host = new URL(repoUrl).hostname.toLowerCase();
  } catch {
    return 'generic';
  }
  if (host === 'dev.azure.com' || host.endsWith('.visualstudio.com')) return 'azure_repos';
  if (host === 'github.com') return 'github';
  if (host === 'gitlab.com') return 'gitlab';
  if (host === 'bitbucket.org') return 'bitbucket';
  return 'generic';
}

export const DEFAULT_USERNAMES: Record<GitHost, string | null> = {
  azure_repos: 'pat',
  github: 'x-access-token',
  gitlab: 'oauth2',
  bitbucket: 'x-token-auth',
  generic: null,
};

export const HOST_LABELS: Record<GitHost, string> = {
  azure_repos: 'Azure Repos',
  github: 'GitHub',
  gitlab: 'GitLab',
  bitbucket: 'Bitbucket Cloud',
  generic: 'Git server',
};

/** The least privilege each host needs: TicketTrail only reads commits. */
export const SECRET_HINTS: Record<GitHost, string> = {
  azure_repos: 'A personal access token with the Code (Read) scope. Any non-empty username works.',
  github: 'A fine-grained or classic token with read access to the repository contents.',
  gitlab: 'A personal or project access token with the read_repository scope.',
  bitbucket: 'An app password or access token with repository read access.',
  generic: 'The password or token for an account that can read the repository.',
};
