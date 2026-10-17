import pytest

from app.integrations.git.hosts import (
    DEFAULT_USERNAMES,
    GitHost,
    commit_url,
    commit_url_pattern,
    detect_host,
    repo_name,
)

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://dev.azure.com/acme/proj/_git/repo", GitHost.AZURE_REPOS),
        ("https://acme.visualstudio.com/proj/_git/repo", GitHost.AZURE_REPOS),
        ("https://github.com/acme/app.git", GitHost.GITHUB),
        ("https://gitlab.com/group/sub/app.git", GitHost.GITLAB),
        ("https://bitbucket.org/acme/app.git", GitHost.BITBUCKET),
        ("https://git.example.com/acme/app.git", GitHost.GENERIC),
        ("https://github.com.evil.example/acme/app.git", GitHost.GENERIC),
    ],
)
def test_detect_host(url: str, host: GitHost) -> None:
    assert detect_host(url) == host


def test_default_usernames_match_spec() -> None:
    assert DEFAULT_USERNAMES[GitHost.AZURE_REPOS] == "pat"
    assert DEFAULT_USERNAMES[GitHost.GITHUB] == "x-access-token"
    assert DEFAULT_USERNAMES[GitHost.GITLAB] == "oauth2"
    assert DEFAULT_USERNAMES[GitHost.BITBUCKET] == "x-token-auth"
    assert DEFAULT_USERNAMES[GitHost.GENERIC] is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://dev.azure.com/acme/proj/_git/repo",
            f"https://dev.azure.com/acme/proj/_git/repo/commit/{SHA}",
        ),
        ("https://github.com/acme/app.git", f"https://github.com/acme/app/commit/{SHA}"),
        ("https://github.com/acme/app/", f"https://github.com/acme/app/commit/{SHA}"),
        (
            "https://gitlab.com/group/sub/app.git",
            f"https://gitlab.com/group/sub/app/-/commit/{SHA}",
        ),
        ("https://bitbucket.org/acme/app.git", f"https://bitbucket.org/acme/app/commits/{SHA}"),
        ("https://git.example.com/acme/app.git", ""),
    ],
)
def test_inferred_commit_urls(url: str, expected: str) -> None:
    assert commit_url(url, None, SHA) == expected


def test_explicit_template_wins() -> None:
    template = "https://gitea.example.com/acme/app/commit/{sha}"
    assert commit_url_pattern("https://github.com/acme/app.git", template) == template
    assert commit_url("https://git.example.com/acme/app.git", template, "abc") == (
        "https://gitea.example.com/acme/app/commit/abc"
    )


def test_repo_name() -> None:
    assert repo_name("https://github.com/acme/tickettrail.git") == "tickettrail"
    assert repo_name("https://dev.azure.com/acme/proj/_git/repo") == "repo"
