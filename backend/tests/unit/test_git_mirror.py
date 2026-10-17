"""GitClient's local-mirror operations against fixture repositories."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.integrations.git.client import GitClient, GitNotFoundError
from tests.fixtures.repos import FixtureRepo


@pytest.fixture
def origin(tmp_path: Path) -> FixtureRepo:
    return FixtureRepo(tmp_path / "origin")


@pytest.fixture
def client() -> GitClient:
    return GitClient(None, timeout=60, allowed_protocols="file")


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    return tmp_path / "mirrors" / "project-1"


def test_mirror_clones_then_fetches(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    first = origin.commit("first AB#1")
    client.mirror(origin.url, mirror)
    assert (mirror / "HEAD").is_file()
    assert [c.sha for c in client.list_commits(mirror, "main")] == [first]

    second = origin.commit("second AB#2")
    client.mirror(origin.url, mirror)  # now only a fetch
    assert [c.sha for c in client.list_commits(mirror, "main")] == [first, second]
    assert not mirror.with_name("project-1.partial").exists()


def _refs(mirror: Path) -> list[str]:
    import subprocess

    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)"], cwd=mirror, capture_output=True, check=True
    )
    return sorted(out.stdout.decode().split())


def test_only_branches_are_copied(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    sha = origin.commit("first")
    origin.git("update-ref", "refs/pull/1/head", sha)  # what GitHub keeps for every PR
    origin.git("tag", "v1.0")
    client.mirror(origin.url, mirror)
    assert _refs(mirror) == ["refs/heads/main"]


def test_fetch_adds_new_branches_and_prunes_deleted_ones(
    origin: FixtureRepo, client: GitClient, mirror: Path
) -> None:
    origin.commit("first")
    origin.checkout("old", create=True)
    client.mirror(origin.url, mirror)
    assert _refs(mirror) == ["refs/heads/main", "refs/heads/old"]

    origin.checkout("new", create=True)
    origin.git("branch", "-D", "old")
    origin.git("update-ref", "refs/pull/2/head", origin.head())
    client.mirror(origin.url, mirror)
    assert _refs(mirror) == ["refs/heads/main", "refs/heads/new"]


def test_failed_clone_leaves_no_mirror(tmp_path: Path, client: GitClient, mirror: Path) -> None:
    with pytest.raises(GitNotFoundError):
        client.mirror((tmp_path / "missing").as_uri(), mirror)
    assert not mirror.exists()


def test_commit_fields(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    sha = origin.commit("Fix login AB#12\n\nThe cookie was dropped.\nSee AB#13.")
    client.mirror(origin.url, mirror)
    [commit] = client.list_commits(mirror, "main")
    assert commit.sha == sha
    assert commit.author_name == "Ada Lovelace"
    assert commit.author_email == "ada@example.com"
    assert commit.author_date == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert commit.committer_date == commit.author_date
    assert commit.subject == "Fix login AB#12"
    assert commit.body == "The cookie was dropped.\nSee AB#13."
    assert commit.message == "Fix login AB#12\n\nThe cookie was dropped.\nSee AB#13."
    assert commit.parent_count == 0
    assert not commit.is_merge


def test_commits_are_oldest_first(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    shas = [origin.commit(f"commit {i}") for i in range(5)]
    client.mirror(origin.url, mirror)
    assert [c.sha for c in client.list_commits(mirror, "main")] == shas


def test_merge_commits_have_two_parents(
    origin: FixtureRepo, client: GitClient, mirror: Path
) -> None:
    origin.commit("base")
    origin.checkout("feature", create=True)
    origin.commit("feature work AB#5")
    origin.checkout("main")
    origin.commit("main work")
    merge = origin.merge("feature", "Merge feature")
    client.mirror(origin.url, mirror)
    commits = {c.sha: c for c in client.list_commits(mirror, "main")}
    assert commits[merge].is_merge
    assert commits[merge].parent_count == 2
    assert sum(c.is_merge for c in commits.values()) == 1


def test_list_after_a_commit(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    first = origin.commit("one")
    second = origin.commit("two")
    third = origin.commit("three")
    client.mirror(origin.url, mirror)
    assert [c.sha for c in client.list_commits(mirror, "main", after_sha=first)] == [second, third]
    assert client.list_commits(mirror, "main", after_sha=third) == []


def test_list_since_a_date(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    origin.commit("Jan 1")
    jan2 = origin.commit("Jan 2")
    jan3 = origin.commit("Jan 3")
    client.mirror(origin.url, mirror)
    since = client.list_commits(mirror, "main", since=date(2026, 1, 2))
    assert [c.sha for c in since] == [jan2, jan3]


def test_branches_and_ancestry(origin: FixtureRepo, client: GitClient, mirror: Path) -> None:
    base = origin.commit("base")
    origin.checkout("dev", create=True)
    on_dev = origin.commit("dev only")
    client.mirror(origin.url, mirror)
    assert client.has_branch(mirror, "dev")
    assert not client.has_branch(mirror, "nope")
    assert client.is_ancestor(mirror, base, "main")
    assert not client.is_ancestor(mirror, on_dev, "main")
    assert not client.is_ancestor(mirror, "0" * 40, "main")
    assert client.has_commit(mirror, on_dev)
    assert not client.has_commit(mirror, "1" * 40)


def test_force_push_makes_the_old_tip_unreachable(
    origin: FixtureRepo, client: GitClient, mirror: Path
) -> None:
    origin.commit("base")
    old_tip = origin.commit("will be rewritten")
    client.mirror(origin.url, mirror)
    assert client.is_ancestor(mirror, old_tip, "main")

    new_tip = origin.rewrite_last("rewritten")
    client.mirror(origin.url, mirror)
    assert not client.is_ancestor(mirror, old_tip, "main")
    assert client.is_ancestor(mirror, new_tip, "main")


def test_non_utf8_messages_do_not_break_listing(
    origin: FixtureRepo, client: GitClient, mirror: Path
) -> None:
    origin.commit(b"Caf\xe9 AB#9")  # Latin-1, not UTF-8
    client.mirror(origin.url, mirror)
    [commit] = client.list_commits(mirror, "main")
    assert commit.subject.startswith("Caf")
    assert commit.subject.endswith("AB#9")
