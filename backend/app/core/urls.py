"""URL rules for repository and Azure URLs, and the SSRF guard (spec section 10)."""

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    pass


def normalise_https_url(url: str) -> str:
    """Check that a URL is https://, has a host and carries no password.

    A bare username (as in Azure clone URLs, https://acme@dev.azure.com/...) is
    dropped: credentials live in the connection's own fields, never in the URL.
    """
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise UnsafeUrlError("must start with https://")
    if not parts.hostname:
        raise UnsafeUrlError("must include a host name")
    if parts.password is not None:
        raise UnsafeUrlError(
            "must not contain a password; enter the token in the secret field instead"
        )
    if parts.fragment:
        raise UnsafeUrlError("must not contain a #fragment")
    netloc = parts.hostname.lower()
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(("https", netloc, parts.path, parts.query, ""))


def _is_private(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def check_public_host(url: str, *, allow_private: bool) -> None:
    """Refuse URLs whose host resolves to a private, loopback or link-local address.

    Called right before the server connects, so the check sees current DNS.
    """
    if allow_private:
        return
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"host {host!r} could not be resolved") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if _is_private(address):
            raise UnsafeUrlError(
                f"host {host!r} resolves to a private address ({address}); "
                "set TT_ALLOW_PRIVATE_HOSTS=true to allow servers on your network"
            )
