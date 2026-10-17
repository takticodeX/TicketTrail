"""Encryption of stored credentials (tokens, PATs, passwords) with Fernet.

Key rotation (spec section 10): set the new key as TT_ENCRYPTION_KEY and the old
one as TT_ENCRYPTION_KEY_OLD. Secrets encrypted with either key keep working;
`python manage.py rotate-keys` then re-encrypts them all with the new key, after
which TT_ENCRYPTION_KEY_OLD can be removed.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import Settings


class SecretDecryptionError(Exception):
    """The ciphertext was not produced with TT_ENCRYPTION_KEY (or TT_ENCRYPTION_KEY_OLD)."""


class SecretBox:
    def __init__(self, key: str, *old_keys: str) -> None:
        # The first key encrypts; every key can decrypt.
        self._fernet = MultiFernet([Fernet(k) for k in (key, *old_keys)])

    @classmethod
    def from_settings(cls, settings: Settings) -> "SecretBox":
        old = settings.encryption_key_old
        return cls(
            settings.encryption_key.get_secret_value(),
            *([old.get_secret_value()] if old else []),
        )

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptionError("stored secret cannot be decrypted") from exc

    def rotate(self, ciphertext: str) -> str:
        """Re-encrypt with the current key (works for ciphertexts made with any known key)."""
        try:
            return self._fernet.rotate(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptionError("stored secret cannot be decrypted") from exc
