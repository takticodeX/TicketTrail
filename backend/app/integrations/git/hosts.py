"""Host detection and commit-URL building.

This is the only host-specific code: TicketTrail talks plain Git to every host.
The frontend mirrors these rules in frontend/src/lib/gitHosts.ts.
"""

from enum import StrEnum
from urllib.parse import urlsplit


class GitHost(StrEnum):
    AZURE_REPOS = "azure_repos"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    GENERIC = "generic"


DEFAULT_USERNAMES: dict[GitHost, str | None] = {
    GitHost.AZURE_REPOS: "pat",
    GitHost.GITHUB: "x-access-token",
    GitHost.GITLAB: "oauth2",
    GitHost.BITBUCKET: "x-token-auth",
    GitHost.GENERIC: None,
}

_COMMIT_PATHS: dict[GitHost, str] = {
    GitHost.AZURE_REPOS: "/commit/{sha}",
    GitHost.GITHUB: "/commit/{sha}",
    GitHost.GITLAB: "/-/commit/{sha}",
    GitHost.BITBUCKET: "/commits/{sha}",
}


def detect_host(repo_url: str) -> GitHost:
    host = (urlsplit(repo_url).hostname or "").lower()
    if host == "dev.azure.com" or host.endswith(".visualstudio.com"):
        return GitHost.AZURE_REPOS
    if host == "github.com":
        return GitHost.GITHUB
    if host == "gitlab.com":
        return GitHost.GITLAB
    if host == "bitbucket.org":
        return GitHost.BITBUCKET
    return GitHost.GENERIC


def _web_base(repo_url: str) -> str:
    parts = urlsplit(repo_url)
    path = parts.path.rstrip("/")
    path = path.removesuffix(".git")
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return f"https://{netloc}{path}"


def commit_url_pattern(repo_url: str, explicit_template: str | None) -> str:
    """The commit link with a {sha} placeholder, or "" when it can't be inferred."""
    if explicit_template:
        return explicit_template
    path = _COMMIT_PATHS.get(detect_host(repo_url))
    return _web_base(repo_url) + path if path else ""


def commit_url(repo_url: str, explicit_template: str | None, sha: str) -> str:
    return commit_url_pattern(repo_url, explicit_template).replace("{sha}", sha)


def repo_name(repo_url: str) -> str:
    """Last path segment without .git, e.g. 'tickettrail'."""
    return _web_base(repo_url).rsplit("/", 1)[-1]
