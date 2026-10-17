"""Administrative commands. Run inside the api container:

python manage.py rotate-keys
"""

import argparse
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.crypto import SecretBox, SecretDecryptionError
from app.db.models import AzureConnection, GitConnection
from app.db.session import create_db_engine, create_session_factory

logger = logging.getLogger("tickettrail.manage")


def rotate_keys(db: Session, box: SecretBox) -> tuple[int, list[str]]:
    """Re-encrypt every stored secret with the current key.

    Returns how many secrets were re-encrypted and the connections whose secret
    could not be decrypted with any configured key (left as they are).
    """
    rotated = 0
    failed: list[str] = []
    for git in db.scalars(select(GitConnection).where(GitConnection.secret_enc.is_not(None))):
        try:
            git.secret_enc = box.rotate(git.secret_enc or "")
            rotated += 1
        except SecretDecryptionError:
            failed.append(f"git connection {git.id} ({git.name})")
    for azure in db.scalars(select(AzureConnection)):
        try:
            azure.pat_enc = box.rotate(azure.pat_enc)
            rotated += 1
        except SecretDecryptionError:
            failed.append(f"azure connection {azure.id} ({azure.name})")
    db.commit()
    return rotated, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description="TicketTrail admin commands")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "rotate-keys",
        help="re-encrypt all secrets with TT_ENCRYPTION_KEY (old ones need TT_ENCRYPTION_KEY_OLD)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "rotate-keys":
        factory = create_session_factory(create_db_engine(settings.database_url))
        with factory() as db:
            rotated, failed = rotate_keys(db, SecretBox.from_settings(settings))
        print(f"Re-encrypted {rotated} secret(s) with the current key.")
        if failed:
            print("Could not decrypt (enter these again in Settings):")
            for name in failed:
                print(f"  - {name}")
            return 1
        if settings.encryption_key_old is not None:
            print("You can now remove TT_ENCRYPTION_KEY_OLD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
