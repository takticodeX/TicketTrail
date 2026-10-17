"""Encryption of stored credentials (tokens, PATs, passwords) with Fernet."""

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class SecretDecryptionError(Exception):
    """The ciphertext was not produced with the current TT_ENCRYPTION_KEY."""


class SecretBox:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls, settings: Settings) -> "SecretBox":
        return cls(settings.encryption_key.get_secret_value())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptionError("stored secret cannot be decrypted") from exc
