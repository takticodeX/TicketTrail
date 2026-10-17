import socket
from typing import Any

import pytest

from app.core.urls import UnsafeUrlError, check_public_host, normalise_https_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/app.git", "https://github.com/acme/app.git"),
        ("  https://GitHub.com/acme/app  ", "https://github.com/acme/app"),
        (
            "https://acme@dev.azure.com/acme/proj/_git/repo",
            "https://dev.azure.com/acme/proj/_git/repo",
        ),
        ("https://git.example.com:8443/a/b.git", "https://git.example.com:8443/a/b.git"),
    ],
)
def test_normalise_accepts_https(url: str, expected: str) -> None:
    assert normalise_https_url(url) == expected


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://github.com/acme/app", "https://"),
        ("git@github.com:acme/app.git", "https://"),
        ("ssh://git@github.com/acme/app", "https://"),
        ("file:///etc/passwd", "https://"),
        ("https://user:hunter2@github.com/acme/app", "password"),
        ("https:///no-host", "host"),
        ("https://github.com/acme/app#frag", "fragment"),
    ],
)
def test_normalise_rejects(url: str, reason: str) -> None:
    with pytest.raises(UnsafeUrlError, match=reason):
        normalise_https_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/repo.git",
        "https://10.1.2.3/repo.git",
        "https://192.168.1.10/repo.git",
        "https://172.16.0.1/repo.git",
        "https://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "https://[::1]/repo.git",
        "https://[::ffff:127.0.0.1]/repo.git",
        "https://0.0.0.0/repo.git",
    ],
)
def test_private_addresses_are_blocked(url: str) -> None:
    with pytest.raises(UnsafeUrlError, match="private address"):
        check_public_host(url, allow_private=False)


def test_private_addresses_allowed_when_configured() -> None:
    check_public_host("https://10.1.2.3/repo.git", allow_private=True)


def _fake_resolver(address: str) -> Any:
    def resolve(*_: Any, **__: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    return resolve


def test_host_name_resolving_to_private_address_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("10.0.0.7"))
    with pytest.raises(UnsafeUrlError, match="private address"):
        check_public_host("https://git.internal.example/repo.git", allow_private=False)


def test_public_host_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("140.82.121.4"))
    check_public_host("https://github.com/acme/app.git", allow_private=False)


def test_unresolvable_host_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: Any, **__: Any) -> Any:
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(UnsafeUrlError, match="could not be resolved"):
        check_public_host("https://nowhere.invalid/repo.git", allow_private=False)
