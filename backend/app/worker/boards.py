"""Opening the tracker client of a board connection, for the worker.

The one place that knows which client serves which kind of board. It also does
what every use needs first: the SSRF guard on the URL and decrypting the secret
in memory only.
"""

from app.core.crypto import SecretDecryptionError
from app.core.urls import UnsafeUrlError, check_public_host
from app.db.models import BoardConnection, BoardKind
from app.integrations.trackers.azure import AzureBoardsClient
from app.integrations.trackers.base import WorkItemTracker
from app.worker.context import WorkerContext

UNDECRYPTABLE = (
    "The saved secret can't be decrypted (was TT_ENCRYPTION_KEY changed?). Enter it again."
)

# How each kind is named in messages, and what its URL is called.
BOARD_LABELS = {BoardKind.AZURE: "Azure DevOps"}
URL_LABELS = {BoardKind.AZURE: "Organization URL"}


class BoardUnavailableError(Exception):
    """The client can't even be opened (URL refused, secret unreadable). Safe to show."""


def board_label(connection: BoardConnection) -> str:
    return BOARD_LABELS.get(BoardKind(connection.kind), connection.kind)


def open_board(
    context: WorkerContext,
    connection: BoardConnection,
    *,
    timeout: float,
    limited: bool = True,
) -> WorkItemTracker:
    """The tracker client for the connection. `limited` shares the per-server slots."""
    kind = BoardKind(connection.kind)
    try:
        check_public_host(connection.url, allow_private=context.settings.allow_private_hosts)
    except UnsafeUrlError as exc:
        raise BoardUnavailableError(f"{URL_LABELS[kind]} refused: {exc}.") from exc
    try:
        secret = context.secret_box.decrypt(connection.secret_enc)
    except SecretDecryptionError as exc:
        raise BoardUnavailableError(UNDECRYPTABLE) from exc
    limiter = context.board_limiter(connection.url) if limited else None
    if kind is BoardKind.AZURE:
        return AzureBoardsClient(
            connection.url,
            connection.scope,
            secret,
            timeout=timeout,
            limiter=limiter,
            sleep=context.sleep,
        )
    raise BoardUnavailableError(f"{kind.value} boards are not supported yet.")
